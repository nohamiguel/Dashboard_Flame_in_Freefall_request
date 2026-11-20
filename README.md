# Flame in Freefall dashboard: link change request

Hi! We put this repo together for our request to update the link to our Space Apps dashboard. Below is what happened, what we changed, and how you can check it yourself.

## What happened

The link we submitted, `https://heating-test-outputs-subscription.trycloudflare.com/`, was a Cloudflare quick tunnel running on one of our laptops. The server restarted, and quick tunnels get a new random address every time they start. So the old link died, and there's no way to get that exact address back. We tried. The name doesn't even exist in DNS anymore.

To get the dashboard back online we moved it to our own domain (`jsons.lat`) through Cloudflare. The dashboard talks to two servers (the chatbot and the Ollama model), so we had to point those URLs at the new addresses.

**That's the only change.** No new features, no data changes, no design changes. Just the server URLs.

## What's in this repo

- `Prefinal/`: the project as it was before the server went down.
  - `Prefinal/dash/index_completo5.html`: the dashboard before the change.
  - `Prefinal/dash/chatbot15PYthon.py`: the chatbot script before the change.
  - We left out the NASA data folders (`PSI-25`, `PSI-68` and the rest). They're about 3 GB and none of them changed.
- `NewDash/`: the dashboard after we updated the URLs.
- `WhatsApp Image 2026-11-19 at *.jpeg`: three screenshots of the change (more on them below).

## About the dates

`index_completo5.html` and `chatbot15PYthon.py` show Nov 19 as their date. That's because we couldn't recover the original files, so these copies were put back together today. It doesn't mean anything else changed. That's exactly why we added the screenshots: they show the change against the version VS Code had saved on Nov 15.

## The exact changes

### Dashboard: `Prefinal/dash/index_completo5.html` → `NewDash/index.html`

Around line 2403:

```diff
-    const OLLAMA_URL = " https://sim-people-satisfaction-connection.trycloudflare.com";   // where Ollama runs (teammate's computer; use http://localhost:11434 if it runs on this one)
+    //https://autos-eclipse-conferences-rush.trycloudflare.com/
+    const OLLAMA_URL = "https://ollama.jsons.lat";
+    //const OLLAMA_URL = " https://sim-people-satisfaction-connection.trycloudflare.com";   // where Ollama runs (teammate's computer; use http://localhost:11434 if it runs on this one)
```

Around line 2442:

```diff
-    const CHATBOT_URL = "http://localhost:8000";   // where chatbot_dataframes.py runs
+    const CHATBOT_URL = "https://datos.jsons.lat";   // where chatbot_dataframes.py runs
```

The two lines starting with `//` are comments. They're just old addresses we left there as notes and they don't do anything.

### Chatbot: `Prefinal/dash/chatbot15PYthon.py` → `NewDash/chatbot_dataframes.py`

Line 30 is the only difference:

```diff
- OLLAMA_OPCIONES = ['http://10.73.206.152:11434']  # se usa la primera que conteste
+ OLLAMA_OPCIONES = ['http://localhost:11434']  # se usa la primera que conteste
```

That line just tells the chatbot where to find Ollama.

### Everything else

The rest of the dashboard files are identical in both folders, byte for byte: `datos.js`, `procesados.js`, the JSON files, the `construir_*.py` build scripts and the files in `explorador/`. The only exception is an older copy of the chatbot script, explained in the notes below.

## The screenshots

They're from VS Code's Timeline (its local file history). Each one compares the last save from **Nov 15, 2026 at 11:53 PM** (left) with the current file (right):

| Screenshot | File | What it shows |
|---|---|---|
| `WhatsApp Image 2026-11-19 at 21.44.37.jpeg` | `index.html` | the `OLLAMA_URL` line |
| `WhatsApp Image 2026-11-19 at 21.45.05.jpeg` | `index.html` | the `CHATBOT_URL` line |
| `WhatsApp Image 2026-11-19 at 21.59.15.jpeg` | `chatbot_dataframes.py` | line 30, `OLLAMA_OPCIONES` |

One thing you might notice: in the first screenshot, the old `OLLAMA_URL` is `http://10.73.206.152:11434`, not the trycloudflare address that's in `index_completo5.html`. Ollama runs on a teammate's laptop, so that address has changed a few times: a local IP in the Nov 15 save, then a trycloudflare tunnel, and now `ollama.jsons.lat`. It only says where the model lives. It doesn't change anything the dashboard does.

## A couple of small notes

- `Prefinal/dash/Chatbot15.html` is the same file as `chatbot15PYthon.py`, just saved with the wrong extension.
- `Prefinal/dash/chatbot_dataframes.py` is an earlier copy from Nov 15. It's also the same script, and only line 30 is different (Ollama at `192.168.79.26`).

## Check it yourself

Clone the repo and run this from its root:

```bash
git diff --no-index Prefinal/dash/index_completo5.html NewDash/index.html
git diff --no-index Prefinal/dash/chatbot15PYthon.py NewDash/chatbot_dataframes.py
```

Thanks for taking the time to look at this.
