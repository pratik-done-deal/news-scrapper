from fastapi import Request
from sqlalchemy import Engine

from .job_manager import JobManager


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


def get_job_manager(request: Request) -> JobManager:
    return request.app.state.job_manager
