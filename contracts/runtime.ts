/**
 * Runtime facts shared by the UI and asserted by the backend tests.
 *
 * The disconnected banner told the operator to run plain uvicorn, which
 * reinstates the `Server: uvicorn` header that `run.py` exists to suppress -
 * the UI was instructing them to undo a fix. Anything the UI tells someone to
 * type lives here, in one place, and a backend test asserts it still matches
 * reality.
 */

/**
 * Folder the backend is started from, relative to the project folder.
 * No drive letter, no absolute path, no machine or old project name: the hint
 * must be true on any machine. Run it from the project folder, with the
 * project's Python (3.12) active.
 */
export const BACKEND_DIR = "backend";

/**
 * The ONLY supported way to start the API.
 *
 * `python -m uvicorn app.main:app` also works but reinstates the server
 * banner, because uvicorn writes that header at the HTTP protocol layer where
 * response middleware cannot remove it. run.py sets server_header=False.
 */
export const BACKEND_ENTRYPOINT = "run.py";

export const START_BACKEND_COMMAND = `cd ${BACKEND_DIR}\npython ${BACKEND_ENTRYPOINT}`;

/** Where the API listens. Loopback only - document text never leaves the host. */
export const API_ORIGIN = "http://127.0.0.1:8000";
export const API_DOCS_URL = `${API_ORIGIN}/docs`;
