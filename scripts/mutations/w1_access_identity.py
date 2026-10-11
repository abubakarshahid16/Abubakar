"""Mutations for W1 access and identity (2026-10-08): #609.

The #441 entries (M2401-M2405, M2413) were removed with the crs-draft route
(#736, F8c row 1).
#609: an upload names at least one discipline, defaulting to the uploader's
own, so no document is left visible to no discipline; the Administration
screen lists any such document first.

Each entry deletes one of those rules; the named tests must notice.
"""

from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_ACCESS = APP / "access.py"
_MAIN = APP / "main.py"
_T = "tests/test_w1_crs_draft_and_upload_discipline.py"
_UPLOADER = FRONTEND_SRC / "components" / "Uploader.tsx"
_CLIENT = FRONTEND_SRC / "api" / "client.ts"
_ADMIN = FRONTEND_SRC / "views" / "AdminView.tsx"
_T_UPLOADER = "src/components/Uploader.disciplines.test.tsx"

MUTATIONS: tuple[Mutation, ...] = (
    # ---------------------------------------------------------------- #609
    Mutation(
        id="M2406", phase=2406,
        description="an upload naming no discipline is accepted",
        path=_ACCESS,
        anchor="    if not names:\n"
               "        raise UploadDisciplineRefused(",
        replacement="    if not names:\n"
                    "        return []\n"
                    "    if False:\n"
                    "        raise UploadDisciplineRefused(",
        target=_T, keyword="no_discipline_is_refused",
        tags=("critical",),
    ),
    Mutation(
        id="M2407", phase=2406,
        description="an engineer may share an upload with any discipline",
        path=_ACCESS,
        anchor="    else:\n        choices = own\n",
        replacement="    else:\n"
                    "        choices = [r[\"name\"] for r in conn.execute(\n"
                    "            \"SELECT name FROM roles WHERE kind = 'discipline' ORDER BY name\")]\n",
        target=_T, keyword="not_in or own_disciplines",
    ),
    Mutation(
        id="M2408", phase=2406,
        description="the chosen disciplines are never granted",
        path=_MAIN,
        anchor="        access.grant_uploaded_document_to_disciplines(\n"
               "            row[\"id\"], discipline_roles, scope.user_id)",
        replacement="        pass",
        target=_T, keyword="chosen_discipline or any_discipline",
    ),
    Mutation(
        id="M2409", phase=2406,
        description="the upload default is not the uploader's own disciplines",
        path=_ACCESS,
        anchor='    return {"choices": choices, "default": own}',
        replacement='    return {"choices": choices, "default": []}',
        target=_T, keyword="own_disciplines",
    ),
    # ------------------------------------------------------------ frontend
    Mutation(
        id="M2410", phase=2410, runner="vitest",
        description="the upload form sends no discipline with the file",
        path=_UPLOADER,
        anchor='    for (const name of disciplines) form.append("disciplines", name);\n',
        replacement="",
        target=_T_UPLOADER, keyword="sends the default discipline with the file",
        tags=("ui",),
    ),
    Mutation(
        id="M2411", phase=2410, runner="vitest",
        description="the upload form starts with nothing ticked instead of the uploader's own",
        path=_UPLOADER,
        anchor='setPicker({ s: "ready", choices: r.data.choices, chosen: r.data.default });',
        replacement='setPicker({ s: "ready", choices: r.data.choices, chosen: [] });',
        target=_T_UPLOADER, keyword="shows the uploader's own discipline, ticked",
        tags=("ui",),
    ),
    Mutation(
        id="M2412", phase=2410, runner="vitest",
        description="the upload is not blocked when no discipline is ticked",
        path=_UPLOADER,
        anchor='    || (picker.s === "ready" && chosen.length === 0);',
        replacement=";",
        target=_T_UPLOADER, keyword="blocks the upload when no discipline is ticked",
        tags=("ui",),
    ),
    Mutation(
        id="M2414", phase=2410, runner="vitest",
        description="documents no discipline can see are not listed first",
        path=_ADMIN,
        anchor="            {orphansFirst(documents).map((doc) => (",
        replacement="            {documents.map((doc) => (",
        target="src/views/AdminView.test.tsx",
        keyword="puts the orphan at the top, with its Grant buttons",
        tags=("ui",),
    ),
)
