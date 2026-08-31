from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.pipeline import parse_pipeline, PipelineParseError

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=schemas.ProjectOut, status_code=201)
def create_project(payload: schemas.ProjectCreate, db: Session = Depends(get_db)):
    try:
        parse_pipeline(payload.pipeline_yaml)
    except PipelineParseError as e:
        raise HTTPException(422, f"invalid pipeline_yaml: {e}")

    project = models.Project(
        name=payload.name,
        repo_url=payload.repo_url,
        default_branch=payload.default_branch,
        pipeline_yaml=payload.pipeline_yaml,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[schemas.ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(models.Project).order_by(models.Project.created_at.desc()).all()


@router.get("/{project_id}", response_model=schemas.ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    return project


@router.put("/{project_id}/pipeline", response_model=schemas.ProjectOut)
def update_pipeline(project_id: str, payload: schemas.PipelineUpdate, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    try:
        parse_pipeline(payload.pipeline_yaml)
    except PipelineParseError as e:
        raise HTTPException(422, f"invalid pipeline_yaml: {e}")
    project.pipeline_yaml = payload.pipeline_yaml
    db.commit()
    db.refresh(project)
    return project
