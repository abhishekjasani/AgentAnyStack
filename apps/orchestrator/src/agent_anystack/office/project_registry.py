"""Project registry + working trees under PROJECTS_ROOT (not inside office/)."""

from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

import yaml

from agent_anystack.domain.project import CreateProjectRequest, ProjectRecord

_REGISTRY_NAME = "projects.yaml"


class ProjectExistsError(Exception):
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(f"project already exists: {project_id}")


class ProjectNotFoundError(Exception):
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(f"project not found: {project_id}")


class ProjectRegistry:
    """office/projects.yaml indexes trees at {projects_root}/{slug}/."""

    def __init__(self, office_root: Path, projects_root: Path) -> None:
        self.office_root = office_root
        self.projects_root = projects_root
        self.registry_path = office_root / _REGISTRY_NAME

    def _load_raw(self) -> list[dict]:
        if not self.registry_path.is_file():
            return []
        data = yaml.safe_load(self.registry_path.read_text(encoding="utf-8")) or {}
        rows = data.get("projects") if isinstance(data, dict) else None
        return list(rows) if isinstance(rows, list) else []

    def _save(self, projects: list[ProjectRecord]) -> None:
        self.office_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "projects": [p.model_dump(mode="json") for p in projects],
        }
        self.registry_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )

    def list_projects(self, *, include_deleted: bool = False) -> list[ProjectRecord]:
        out: list[ProjectRecord] = []
        for row in self._load_raw():
            if not isinstance(row, dict):
                continue
            try:
                rec = ProjectRecord.model_validate(row)
            except Exception:  # noqa: BLE001 — skip corrupt rows
                continue
            if not include_deleted and rec.status != "active":
                continue
            out.append(rec)
        return out

    def get(self, project_id: str) -> ProjectRecord | None:
        pid = (project_id or "").strip()
        for p in self.list_projects(include_deleted=True):
            if p.id == pid:
                return p
        return None

    def require_active(self, project_id: str) -> ProjectRecord:
        rec = self.get(project_id)
        if rec is None or rec.status != "active":
            raise ProjectNotFoundError(project_id)
        return rec

    def create(self, req: CreateProjectRequest) -> ProjectRecord:
        name = req.name.strip()
        slug = (req.slug or _slugify(name)).strip()
        if not re.match(r"^[a-z][a-z0-9_-]*$", slug):
            raise ValueError(f"invalid project slug: {slug}")

        existing = self.list_projects(include_deleted=True)
        # Unique folder: if slug taken, append short id.
        folder_slug = slug
        used_slugs = {p.slug for p in existing}
        if folder_slug in used_slugs:
            folder_slug = f"{slug}-{uuid.uuid4().hex[:6]}"

        project_id = f"{slug}-{uuid.uuid4().hex[:8]}"
        if any(p.id == project_id for p in existing):
            raise ProjectExistsError(project_id)

        self.projects_root.mkdir(parents=True, exist_ok=True)
        root = self.projects_root.resolve()
        tree = (root / folder_slug).resolve()
        if root not in tree.parents:
            raise ValueError("project path escapes PROJECTS_ROOT")
        tree.mkdir(parents=False, exist_ok=False)
        _git_init(tree)
        (tree / "README.md").write_text(
            f"# {name}\n\nAgentAnyStack project working tree (git). LFS optional later.\n",
            encoding="utf-8",
        )

        # Path as configured for the runtime (compose: /projects/<slug>).
        path = f"{str(self.projects_root).rstrip('/').rstrip(chr(92))}/{folder_slug}".replace(
            "\\", "/"
        )        rec = ProjectRecord(
            id=project_id,
            name=name,
            slug=folder_slug,
            path=path,
            status="active",
        )
        existing.append(rec)
        self._save(existing)
        return rec


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (s[:48] or "project").rstrip("-")


def _git_init(tree: Path) -> None:
    try:
        subprocess.run(
            ["git", "init"],
            cwd=tree,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "git is required to create a project working tree (install git in the image/host)"
        ) from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"git init failed: {err}") from exc
