"""Service B (render) — Modal serverless GPU endpoint + Service A client.

Import only `render.client` from Service A (pure stdlib, no heavy deps). `render.modal_app`
imports `modal` and is used only for `modal deploy`, never by the FastAPI service — so this
package intentionally does NOT import it here.
"""
