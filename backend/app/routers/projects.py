from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Project, User, gen_id
from ..schemas import CreateProjectIn, ProjectOut, TenderUploadMetaOut, UpdateProjectIn

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _to_project_out(project: Project) -> ProjectOut:
    tender_doc = TenderUploadMetaOut(**project.tender_doc_json) if project.tender_doc_json else None
    return ProjectOut(
        id=project.id,
        code=project.code,
        name=project.name,
        type=project.type,
        owner=project.owner or "",
        budget=project.budget or "待定",
        deadline=project.deadline or "",
        progress=project.progress or 0,
        score=project.score or 0,
        status=project.status or "撰写中",
        createdAt=project.created_at.strftime("%Y-%m-%d") if project.created_at else "",
        tenderDoc=tender_doc,
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[ProjectOut]:
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return [_to_project_out(p) for p in projects]


@router.post("", response_model=ProjectOut)
def create_project(
    payload: CreateProjectIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectOut:
    project = Project(
        id=gen_id("proj"),
        code=payload.code.strip(),
        name=payload.name.strip(),
        type=payload.type,
        owner=payload.owner or current_user.name,
        owner_id=current_user.id,
        budget=f"¥ {payload.budget} 万" if payload.budget else "待定",
        deadline=payload.deadline or "2026-12-31",
        progress=0,
        score=0,
        status="撰写中",
        tender_doc_json=payload.tenderDoc.model_dump() if payload.tenderDoc else None,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _to_project_out(project)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> ProjectOut:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    return _to_project_out(project)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    payload: UpdateProjectIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectOut:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")

    data = payload.model_dump(exclude_unset=True)
    if "tenderDoc" in data:
        tender_doc = data.pop("tenderDoc")
        project.tender_doc_json = tender_doc
    for field, value in data.items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return _to_project_out(project)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    db.delete(project)
    db.commit()
