"""Human directory entries; these records do not grant access or imply live presence."""

import sqlite3
from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.memory import sqlite_path_from_database_url

router = APIRouter(tags=["people"])


class PersonIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=64)
    name: str = Field(min_length=1, max_length=100)
    team: str = Field(default="eng", pattern=r"^[a-z][a-z0-9_-]*$", max_length=64)
    title: str = Field(default="Team member", min_length=1, max_length=100)


class PersonOut(PersonIn):
    is_current: bool = False
    registered: bool = True


def directory(settings: Annotated[Settings, Depends(get_settings)]):
    path = sqlite_path_from_database_url(settings.database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5, check_same_thread=False)) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS people (id TEXT PRIMARY KEY, name TEXT NOT NULL, team TEXT NOT NULL, title TEXT NOT NULL)"
        )
        yield db


@router.get("/office/people", response_model=list[PersonOut])
def list_people(
    db: Annotated[sqlite3.Connection, Depends(directory)],
    user_id: Annotated[str, Depends(get_user_id)],
):
    people = [
        PersonOut(id=r[0], name=r[1], team=r[2], title=r[3], is_current=r[0] == user_id)
        for r in db.execute(
            "SELECT id, name, team, title FROM people ORDER BY name, id"
        )
    ]
    if not any(p.is_current for p in people):
        people.insert(
            0,
            PersonOut(
                id=user_id,
                name=user_id,
                team="eng",
                title="Current operator",
                is_current=True,
                registered=False,
            ),
        )
    return people


@router.post(
    "/office/people", response_model=PersonOut, status_code=status.HTTP_201_CREATED
)
def add_person(
    body: PersonIn,
    db: Annotated[sqlite3.Connection, Depends(directory)],
    user_id: Annotated[str, Depends(get_user_id)],
):
    try:
        db.execute(
            "INSERT INTO people VALUES (?, ?, ?, ?)",
            (body.id, body.name, body.team, body.title),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "A person with that ID is already listed.") from exc
    return PersonOut(**body.model_dump(), is_current=body.id == user_id)


@router.delete("/office/people/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_person(
    person_id: str,
    db: Annotated[sqlite3.Connection, Depends(directory)],
    _user_id: Annotated[str, Depends(get_user_id)],
):
    result = db.execute("DELETE FROM people WHERE id = ?", (person_id,))
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "Directory entry not found.")
