from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session, select

from .models import (
    init_db,
    get_engine,
    get_session,
    User,
    Order,
    Note,
)
from .auth import (
    get_password_hash,
    verify_password,
    require_logged_in_user,
    require_admin_user,
    get_current_user_optional,
)


app = FastAPI(title="Pasūtījumu un termiņu uzskaite")

app.add_middleware(SessionMiddleware, secret_key="change-this-session-secret")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def on_startup() -> None:
    engine = get_engine()
    init_db(engine)
    # Noklusējuma administrators
    with Session(engine) as session:
        admin_exists = session.exec(select(User).where(User.role == "admin")).first()
        if not admin_exists:
            default_admin = User(
                email="admin@example.com",
                name="Admins",
                password_hash=get_password_hash("admin123"),
                role="admin",
            )
            session.add(default_admin)
            session.commit()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user: Optional[User] = Depends(get_current_user_optional)):
    if user:
        return RedirectResponse(url="/panelis", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/pieslegties", status_code=status.HTTP_302_FOUND)


@app.get("/pieslegties", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/pieslegties")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    with get_session() as session:
        user = session.exec(select(User).where(User.email == email)).first()
        if not user or not verify_password(password, user.password_hash):
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Nepareizs e-pasts vai parole"},
                status_code=400,
            )
        request.session["user_id"] = user.id
        return RedirectResponse(url="/panelis", status_code=status.HTTP_302_FOUND)


@app.get("/iziet")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/pieslegties", status_code=status.HTTP_302_FOUND)


@app.get("/panelis", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: User = Depends(require_logged_in_user)):
    with get_session() as session:
        if current_user.role == "admin":
            orders = session.exec(select(Order).order_by(Order.deadline)).all()
            users = session.exec(select(User).order_by(User.name)).all()
            return templates.TemplateResponse(
                "dashboard_admin.html",
                {
                    "request": request,
                    "user": current_user,
                    "orders": orders,
                    "users": users,
                },
            )
        else:
            orders = (
                session.exec(
                    select(Order).where(Order.assignee_id == current_user.id).order_by(Order.deadline)
                ).all()
            )
            return templates.TemplateResponse(
                "dashboard_user.html",
                {"request": request, "user": current_user, "orders": orders},
            )


@app.get("/pasutijumi/jauns", response_class=HTMLResponse)
async def new_order_form(request: Request, current_user: User = Depends(require_admin_user)):
    with get_session() as session:
        users = session.exec(select(User).order_by(User.name)).all()
        return templates.TemplateResponse("order_new.html", {"request": request, "user": current_user, "users": users})


@app.post("/pasutijumi/jauns")
async def create_order(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    deadline: str = Form(...),
    type: str = Form(...),
    assignee_id: Optional[int] = Form(None),
    current_user: User = Depends(require_admin_user),
):
    with get_session() as session:
        deadline_dt = datetime.fromisoformat(deadline)
        order = Order(
            title=title,
            description=description,
            status="pending",
            deadline=deadline_dt,
            type=type,
            assignee_id=assignee_id,
            created_by_id=current_user.id,
        )
        session.add(order)
        session.commit()
        return RedirectResponse(url="/panelis", status_code=status.HTTP_302_FOUND)


@app.get("/pasutijumi/{order_id}", response_class=HTMLResponse)
async def order_detail(order_id: int, request: Request, current_user: User = Depends(require_logged_in_user)):
    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Pasūtījums nav atrasts")
        notes = session.exec(select(Note).where(Note.order_id == order_id).order_by(Note.created_at.desc())).all()
        users = session.exec(select(User).order_by(User.name)).all() if current_user.role == "admin" else []
        return templates.TemplateResponse(
            "order_detail.html",
            {"request": request, "user": current_user, "order": order, "notes": notes, "users": users},
        )


@app.post("/pasutijumi/{order_id}/pieskirt")
async def assign_order(order_id: int, assignee_id: Optional[int] = Form(None), current_user: User = Depends(require_admin_user)):
    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Pasūtījums nav atrasts")
        order.assignee_id = assignee_id
        session.add(order)
        session.commit()
        return RedirectResponse(url=f"/pasutijumi/{order_id}", status_code=status.HTTP_302_FOUND)


@app.post("/pasutijumi/{order_id}/termins")
async def update_deadline(order_id: int, deadline: str = Form(...), current_user: User = Depends(require_admin_user)):
    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Pasūtījums nav atrasts")
        order.deadline = datetime.fromisoformat(deadline)
        session.add(order)
        session.commit()
        return RedirectResponse(url=f"/pasutijumi/{order_id}", status_code=status.HTTP_302_FOUND)


@app.post("/pasutijumi/{order_id}/statuss")
async def update_status(order_id: int, status_value: str = Form(...), current_user: User = Depends(require_logged_in_user)):
    allowed_statuses = {"pending", "in_progress", "shipped", "completed", "cancelled"}
    if status_value not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Nederīgs statuss")
    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Pasūtījums nav atrasts")
        if current_user.role != "admin" and order.assignee_id != current_user.id:
            raise HTTPException(status_code=403, detail="Nav atļauts atjaunināt šo pasūtījumu")
        order.status = status_value
        session.add(order)
        session.commit()
        return RedirectResponse(url=f"/pasutijumi/{order_id}", status_code=status.HTTP_302_FOUND)


@app.post("/pasutijumi/{order_id}/piezimes")
async def add_note(order_id: int, content: str = Form(...), current_user: User = Depends(require_logged_in_user)):
    if not content.strip():
        raise HTTPException(status_code=400, detail="Nepieciešams piezīmes saturs")
    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Pasūtījums nav atrasts")
        note = Note(order_id=order_id, user_id=current_user.id, content=content.strip())
        session.add(note)
        session.commit()
        return RedirectResponse(url=f"/pasutijumi/{order_id}", status_code=status.HTTP_302_FOUND)


# Vienkāršots kadastra importa stubs: aizpilda lokācijas laukus pēc ievadītā ID

def _fake_lookup_cadastre(cadastre_id: str):
    cadastre_id = cadastre_id.strip()
    if not cadastre_id:
        return None, None, None
    # Deterministiska pseido-ģeolokācija Latvijā
    base = sum(ord(c) for c in cadastre_id)
    lat = 56.8 + (base % 100) * 0.001
    lng = 24.0 + (base % 150) * 0.001
    address = f"Kadastra ID {cadastre_id}"
    return address, lat, lng


@app.post("/pasutijumi/{order_id}/kadastrs")
async def import_from_cadastre(order_id: int, cadastre_id: str = Form(...), current_user: User = Depends(require_admin_user)):
    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Pasūtījums nav atrasts")
        address, lat, lng = _fake_lookup_cadastre(cadastre_id)
        order.cadastre_id = cadastre_id.strip()
        order.location_address = address
        order.location_lat = lat
        order.location_lng = lng
        session.add(order)
        session.commit()
        return RedirectResponse(url=f"/pasutijumi/{order_id}", status_code=status.HTTP_302_FOUND)