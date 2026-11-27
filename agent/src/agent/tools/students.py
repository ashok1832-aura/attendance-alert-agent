"""Tool 2: find students below an attendance % (Azure SQL)."""

import json
import time
from typing import Annotated

import mssql_python
from agent_framework import tool
from pydantic import Field

from src.agent.credential import get_credential
from src.config.config import get_config

QUERY = """
SELECT student_id, full_name, email, regulation, attendance_pct
FROM dbo.students
WHERE attendance_pct < ? AND regulation = ?
ORDER BY attendance_pct
"""


def connect():
    cfg = get_config()
    conn_str = f"Server={cfg.sql_server};Database={cfg.sql_database};Encrypt=yes;"
    # The database pauses when idle, so retry for about a minute while it wakes up.
    for attempt in range(6):
        try:
            return mssql_python.connect(conn_str, token_provider=get_credential(), timeout=60)
        except mssql_python.OperationalError as error:
            if "not currently available" not in str(error) or attempt == 5:
                raise
            time.sleep(10)


@tool(approval_mode="never_require")
def get_students_below_attendance(
    threshold_pct: Annotated[float, Field(description="Minimum attendance % found in the regulations.")],
    regulation: Annotated[str, Field(description="Regulation code the rule applies to, e.g. 'R22'.")],
) -> str:
    """Return the students whose attendance is strictly below threshold_pct, lowest first, as JSON."""
    with connect() as conn:
        cursor = conn.cursor()
        cursor.execute(QUERY, (threshold_pct, regulation))  # parameterised: safe from SQL injection
        columns = [column[0] for column in cursor.description]
        students = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    return json.dumps(students, default=float)
