"""The mutation registry for `scripts/mutation_check.py`.

README: new mutations go in the file for the module they mutate (e.g. an edit
to backend/app/datasheets.py goes in `datasheets.py`; a module with fewer than
three mutations goes in `misc.py`, any frontend file in `frontend.py`). Ids
stay globally unique - the harness refuses a duplicate at import. Next free id:
`grep -rhoE 'id="M[0-9]+"' scripts/mutations | sort -V | tail -1`, plus one.

Each module defines `MUTATIONS: tuple[Mutation, ...]`; the harness imports
every non-underscore module here, sorted, and concatenates them. Shared types,
paths and quoted anchors are in `_base.py`.
"""
