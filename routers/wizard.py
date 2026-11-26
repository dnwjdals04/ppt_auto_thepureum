import datetime

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _store(request: Request):
    return request.app.state.store


@router.get("/")
def step1(request: Request):
    today = datetime.date.today()
    next_sunday = today + datetime.timedelta(days=(6 - today.weekday()) % 7)
    return templates.TemplateResponse(
        request=request,
        name="step1.html",
        context={"default_date": next_sunday.isoformat()},
    )


@router.get("/step/2")
def step2(request: Request, plan_id: str):
    store = _store(request)
    plan = store.get(plan_id)

    if not plan:
        return templates.TemplateResponse(
            request=request,
            name="step2.html",
            context={"plan_id": plan_id, "error": "plan not found"},
        )

    praise_count = int(plan.get("praise_count", 3))
    conti_songs = plan.get("conti_songs") or []
    conti_songs = conti_songs + [{"title": "", "form": ""}] * (praise_count - len(conti_songs))
    return templates.TemplateResponse(
        request=request,
        name="step2.html",
        context={"plan_id": plan_id, "praise_count": praise_count, "conti_songs": conti_songs},
    )


@router.get("/step/3")
def step3(request: Request, plan_id: str):
    store = _store(request)
    plan = store.get(plan_id)

    if not plan:
        return templates.TemplateResponse(
            request=request,
            name="step3.html",
            context={"plan_id": plan_id, "error": "plan not found"},
        )

    # 템플릿에서 plan.songs.praise / plan.songs.offering / plan.songs.closing 사용
    return templates.TemplateResponse(
        request=request,
        name="step3.html",
        context={"plan_id": plan_id, "plan": plan},
    )


@router.get("/step/4")
def step4(request: Request, plan_id: str):
    store = _store(request)
    plan = store.get(plan_id)
    return templates.TemplateResponse(
        request=request,
        name="step4.html",
        context={
            "plan_id": plan_id,
            "has_plan": plan is not None,
            "date_str": (plan or {}).get("date", "").replace("-", ""),
        },
    )