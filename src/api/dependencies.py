from fastapi import HTTPException, Request

from .job_manager import JobManager
from ..db.mysql_dao import MySQLDAO
from ..db.queries import Neo4jConnection


def get_connection(request: Request) -> Neo4jConnection:
    return request.app.state.conn


def get_mysql_dao(request: Request) -> MySQLDAO:
    """Company MySQL DAO, or 503 when the service started without MySQL configured."""
    dao = getattr(request.app.state, "mysql_dao", None)
    if dao is None:
        raise HTTPException(status_code=503, detail="Company MySQL database is not configured")
    return dao


def get_job_manager(request: Request) -> JobManager:
    return request.app.state.job_manager
