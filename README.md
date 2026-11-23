# AeroPrice AI

**AeroPrice AI** is an autonomous pricing platform for aerospace spare parts. A team
of AI agents work together to look up a part, check inventory, review cost and
price history, recommend a price, and decide whether that price can be
auto-approved or needs a human pricing leader to sign off on it.

Built with: Python (FastAPI), SQLite, vanilla HTML/CSS/JavaScript, and OpenAI's
API for the "thinking" parts of each agent.

---

## What you need before you start

1. **Python 3.11 or newer** installed on your computer.
2. **Git** installed (to download the code).
3. An **OpenAI API key** (free to create, needs a small amount of credit added to
   actually make requests). Get one at https://platform.openai.com/api-keys

Not sure if you already have Python or Git? Open a terminal and type:

```
python3 --version
git --version
```

If you see version numbers (like `Python 3.12.1`), you're good. If you see
"command not found", install them first:

- **Python**: https://www.python.org/downloads/ (when installing on Windows,
  make sure to check the box that says **"Add Python to PATH"**)
- **Git**: https://git-scm.com/downloads

---

## Step-by-step setup

### On Mac

Open the **Terminal** app (search for it with Spotlight: `Cmd + Space`, type
"Terminal").

**1. Download the code**

```bash
git clone https://github.com/bibek-p/aeroprice-ai.git
cd aeroprice-ai
```

**2. Create a virtual environment** (a clean, separate space just for this
project's Python packages, so it doesn't mess with anything else on your
computer)

```bash
python3 -m venv venv
source venv/bin/activate
```

Your terminal prompt should now start with `(venv)` — that means it worked.

**3. Install the required packages**

```bash
pip install -r requirements.txt
```

**4. Add your OpenAI API key**

```bash
cp .env.example .env
```

Now open the new `.env` file in any text editor (TextEdit, VS Code, etc.) and
paste your real API key in, so it looks like:

```
OPENAI_API_KEY=sk-your-real-key-here
```

Save the file.

**5. Build the database** (creates a realistic set of sample aerospace parts to
price)

```bash
python3 scripts/build_database.py
```

**6. Create your admin login**

```bash
python3 scripts/create_admin.py admin MyPassword123 "Your Name"
```

(You can use any username/password/name you want — just remember them.)

**7. Start the app**

```bash
uvicorn web.server:app --port 8010
```

**8. Open it in your browser**

Go to: **http://localhost:8010**

Sign in with the username and password you created in step 6. 🎉

To stop the server later, go back to the terminal and press `Ctrl + C`.

---

### On Windows

Open **PowerShell** (search for it in the Start menu).

**1. Download the code**

```powershell
git clone https://github.com/bibek-p/aeroprice-ai.git
cd aeroprice-ai
```

**2. Create a virtual environment**

```powershell
python -m venv venv
venv\Scripts\activate
```

Your prompt should now start with `(venv)` — that means it worked.

> If you get an error like "running scripts is disabled on this system," open
> PowerShell **as Administrator** and run this once:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
> then try `venv\Scripts\activate` again.

**3. Install the required packages**

```powershell
pip install -r requirements.txt
```

**4. Add your OpenAI API key**

```powershell
copy .env.example .env
```

Open the new `.env` file in Notepad (or any text editor) and paste your real
key in:

```
OPENAI_API_KEY=sk-your-real-key-here
```

Save the file.

**5. Build the database**

```powershell
python scripts\build_database.py
```

**6. Create your admin login**

```powershell
python scripts\create_admin.py admin MyPassword123 "Your Name"
```

**7. Start the app**

```powershell
uvicorn web.server:app --port 8010
```

**8. Open it in your browser**

Go to: **http://localhost:8010**

Sign in with the username and password you created in step 6. 🎉

To stop the server later, go back to PowerShell and press `Ctrl + C`.

---

## Coming back later

Once everything is set up, you don't need to repeat all the steps every time.
Just:

**Mac:**
```bash
cd aeroprice-ai
source venv/bin/activate
uvicorn web.server:app --port 8010
```

**Windows:**
```powershell
cd aeroprice-ai
venv\Scripts\activate
uvicorn web.server:app --port 8010
```

Then open http://localhost:8010 again.

---

## Running the automated tests (optional)

If you want to check that everything is working correctly:

```bash
pytest
```

You should see something like `58 passed`.

---

## How it's organized

```
agents/     -- the AI agents and all the pricing/business logic
web/        -- the FastAPI server, HTML pages, and JavaScript/CSS
scripts/    -- one-time setup scripts (build the database, create an admin)
tests/      -- the automated test suite
data/       -- the SQLite database lives here once you build it
```

## Troubleshooting

- **"Address already in use" when starting the server** — something is already
  running on port 8010. Either stop that process, or start on a different port:
  `uvicorn web.server:app --port 8020` (then use that port in your browser URL).
- **Login page says "Create the first admin account" every time** — this means
  no admin has been created yet in `data/pricing.db`. Re-run step 6.
- **"OPENAI_API_KEY not set" or pricing requests fail** — double check your
  `.env` file has the key pasted in correctly with no extra spaces or quotes.
