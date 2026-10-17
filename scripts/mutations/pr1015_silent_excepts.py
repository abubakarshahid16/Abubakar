"""PR #1015 (#655): silent `except X: pass` handlers in the two socket modules
now log their error type. Each entry puts one `pass` back; the guard test (or
the behaviour test for the reader's error body) must notice."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w3_633_silent_excepts.py"
_TAG = ("honesty",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1015-01", phase=1015, description="the model transport's cancel watcher swallows a shutdown error again",
             path=APP / "model_transport.py",
             anchor='                    except OSError as exc:  # #655: already closed by the peer\n'
                    '                        log.debug("cancel: socket shutdown skipped (%s)", type(exc).__name__)\n'
                    '                self.client.close()\n',
             replacement='                    except OSError:\n                        pass\n                self.client.close()\n',
             target=_T, keyword="no_new_silent_handler", tags=_TAG),
    Mutation(id="M1015-02", phase=1015, description="the reader stream's cancel watcher swallows a shutdown error again",
             path=APP / "reader_transport.py",
             anchor='                    except OSError as exc:  # #655: already closed by the peer\n'
                    '                        log.debug("cancel: socket shutdown skipped (%s)", type(exc).__name__)\n'
                    '                client.close()\n',
             replacement='                    except OSError:\n                        pass\n                client.close()\n',
             target=_T, keyword="no_new_silent_handler", tags=_TAG),
    Mutation(id="M1015-03", phase=1015, description="a reader error body that is not JSON leaves no trace (_send)",
             path=APP / "reader_transport.py",
             anchor='\n            except ValueError as exc:  # #655: the status alone is reported\n'
                    '                log.debug("error body from %s was not JSON (%s)", host, type(exc).__name__)\n',
             replacement='\n            except ValueError:\n                pass\n',
             target=_T, keyword="not_json or no_new_silent_handler", tags=_TAG),
    Mutation(id="M1015-04", phase=1015, description="a reader error body that is not JSON leaves no trace (batch _gated)",
             path=APP / "reader_transport.py",
             anchor='\n        except ValueError as exc:  # #655: the status alone is reported\n'
                    '            log.debug("error body from %s was not JSON (%s)", host, type(exc).__name__)\n',
             replacement='\n        except ValueError:\n            pass\n',
             target=_T, keyword="no_new_silent_handler", tags=_TAG),
)
