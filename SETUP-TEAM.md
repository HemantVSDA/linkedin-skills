# AccountIF team setup: LinkedIn Skills in Claude Desktop

For anyone at AccountIF who wants to write LinkedIn posts, comments and on-brand
images with Claude, from their own laptop. No coding needed. About 20 minutes,
once.

What you get: Claude drafts posts in the AccountIF voice, makes images with the
AccountIF logo and colours, and publishes to LinkedIn **only after you approve**.

---

## What you need first

| Item | Where to get it |
|---|---|
| **Claude Desktop** with a paid plan (Pro, Max, Team or Enterprise) | [claude.ai/download](https://claude.ai/download) |
| **Python 3.12** | [python.org/downloads](https://www.python.org/downloads/). On the first install screen, **tick "Add python.exe to PATH"** |
| **Git** | [git-scm.com/download/win](https://git-scm.com/download/win). Click Next through the defaults |
| **Your `.env` file** (keys) | Ask your admin. It is shared privately, never on GitHub |

The AccountIF voice profile (how AccountIF writes) and Story Bank (facts,
figures, naming rules) come with the download, in the `references` folder.
Only the keys are shared separately.

---

## Step 1: Download the skills

1. Press the **Windows key**, type `cmd`, press **Enter**. A black window opens.
2. Copy and paste these lines one at a time, pressing **Enter** after each:

```
cd %USERPROFILE%\Desktop
git clone https://github.com/HemantVSDA/linkedin-skills.git
cd linkedin-skills
python -m pip install -r requirements.txt
```

You now have a folder **`linkedin-skills`** on your Desktop. The last line
takes a minute or two.

## Step 2: Add your `.env` file

Put the **`.env`** file your admin gave you directly inside
`Desktop\linkedin-skills\` (next to `README.md`).

If you don't see `.env` after copying: in File Explorer, click **View → Show →
File name extensions** and **Hidden items**. The file is named exactly `.env`
(no `.txt` at the end).

## Step 3: Your keys (inside `.env`)

Open `.env` with Notepad. It needs these lines filled in:

| Line | What it does | Where it comes from |
|---|---|---|
| `GEMINI_API_KEY=` | Makes the images | Google AI Studio → API Keys (billing must be linked) |
| `PUBLORA_API_KEY=` and `LINKEDIN_PLATFORM_ID=` | Publishes to LinkedIn | [app.publora.com](https://app.publora.com) → Settings → API, and Channels |
| `APIFY_TOKEN=` | Reads other people's posts (for comments) | [console.apify.com](https://console.apify.com) → Settings → Integrations |

> ⚠️ **Publora decides whose LinkedIn the post goes to.** The key and platform
> id belong to one LinkedIn account. Use **your own** Publora account to post as
> yourself, or the AccountIF company page connection your admin gives you.
> Never use someone else's personal key.

Every key is optional. Without one, that step falls back to "here is the draft,
copy-paste it yourself". Nothing breaks.

The `BRAND_...` lines (logo, colours, handle) are already filled in for
AccountIF. Leave them as they are.

## Step 4: Connect the skills to Claude Desktop

1. Open **Claude Desktop**.
2. Top-left, click the **`</>`** icon (the **Code** tab). Not Chat or Cowork:
   only the Code tab can use the files and keys on your laptop.
3. Choose the folder **`Desktop\linkedin-skills`**, and pick **Local** if asked.
4. In the message box, type these two lines, one at a time:

```
/plugin marketplace add ./
```
```
/plugin install linkedin-skills@linkedin-skills
```

5. Close that conversation and start a **new** one in the same folder.

## Step 5: Check everything works

In the Code tab, type:

```
Run python scripts/check_config.py and tell me in simple words what works.
```

You should see **image backend: google**, and **publish backend: publora** if
you added Publora. Allow Claude to run the command when it asks.

## Step 6: Your first post

```
Write a LinkedIn post for AccountIF using the post-writer skill.
Topic: Profit does not always equal cash.
Make an image for it. Show me the draft and the image.
Do not publish until I approve.
```

- Claude asks permission to run commands (to make the image): click **Allow**.
- Images are saved in `linkedin-skills\output\images\`.
- Ask for changes in plain words: *"shorter hook"*, *"change the image headline"*.
- To publish, type **"post"**, or *"schedule it for Tuesday 8:00 AM Toronto
  time"*. If you say nothing, nothing is published.

---

## Updating later

When your admin says there is a new version, open the Code tab in the
`linkedin-skills` folder and type:

```
Run git pull, then reinstall the linkedin-skills plugin from this folder
(/plugin marketplace update linkedin-skills and /plugin update linkedin-skills@linkedin-skills).
```

Your `.env` is never overwritten. The voice profile and Story Bank update with
the rest, so everyone writes from the same facts.

## House rules (already built in)

- Company voice ("we", "AccountIF"), Canadian spelling.
- Never "CPA", never promised outcomes, no client names without written consent.
- Tax posts end with "General information, not tax advice."
- Numbers on images are either typeset or checked by a text reader, never
  unverified.

## Trouble?

| Problem | Fix |
|---|---|
| `python` or `git` "is not recognized" | Reinstall it and tick **Add to PATH**, then open a new `cmd` window |
| Skills don't appear | You are in Chat, not the Code tab; or start a new conversation after Step 4 |
| `/plugin marketplace add ./` fails | Use the full path instead: `/plugin marketplace add C:\Users\YOURNAME\Desktop\linkedin-skills` |
| Image says "manual" | `GEMINI_API_KEY` missing or billing not linked in AI Studio. Run the check in Step 5 |
| Posts go to the wrong LinkedIn | The Publora key in your `.env` belongs to someone else: use your own |
| Anything else | Run the check in Step 5 and send the output to your admin |
