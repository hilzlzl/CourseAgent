# Installation and usage

[简体中文](quickstart.md) · English

## 1. Environment

Use Ubuntu / Debian or Windows WSL2 with Python 3.11+. If virtual environment creation fails because `ensurepip` is missing, install the system `python3-venv` package first. Python is sufficient for the interface, ordinary questions and document export. Executing programming solutions also requires Linux bubblewrap; platform delivery requires Node.js 20+ and Chrome. Browser components are optional for local ordinary-question generation and the fixed demo.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
python -m pip install --no-deps -e .
python -m scripts.doctor
python -m scripts.demo
bash start.sh
```

The first launch creates an empty `data/review.json`, an empty source list and an Excel template generated in code, preserving existing files. Local working data stays in Git-ignored directories. `requirements.lock.txt` is a release dependency snapshot for Linux / Python 3.12, rather than a lock for the historical experiment environment. For other environments, use the compatible version ranges in `requirements.txt`.

`start.cmd` launches the application through WSL on Windows; install the dependencies inside WSL first. Use `bash start.sh --port 8877` to change the port. Ctrl+C stops the API and Worker started by that launch. Avoid running the same workspace from multiple paths simultaneously. In WSL, consistently use the same path and letter case to avoid SQLite WAL aliasing on Windows-mounted drives.

## 2. Model configuration

```bash
cp model-config.example.json model-config.local.json
```

Set `base_url`, `model` and `api_key` in the same JSON object. The example uses a DeepSeek-compatible service; you can use another HTTPS service supporting Chat Completions. Set `base_url` to the API prefix, such as `https://provider.example/v1`, without appending `/chat/completions`. The model must return JSON as requested; field behavior depends on the provider.

```bash
python -m scripts.check_model_connection --check-only  # Validate configuration without network access
python -m scripts.check_model_connection             # Send one real request, consuming model quota
```

You can override these fields with `EDUCODER_MODEL_BASE_URL`, `EDUCODER_MODEL_MODEL` and `EDUCODER_MODEL_API_KEY`. When using environment variables without a configuration file, also select a `backend` explicitly. Keeping `"backend": "langchain"` from the example is recommended. By default, `trust_env: false` prevents inheriting system proxy settings; set it to `true` if your network requires them. Keep keys out of frontend code, screenshots and commit history.

## 3. Programming verification

On Ubuntu / WSL, install:

```bash
sudo apt-get update
sudo apt-get install -y bubblewrap gcc g++
# Install a JDK, such as openjdk-21-jdk, when source solutions require Java
python -m scripts.doctor --programming
```

This check runs a fixed hello-world program in isolation with zero API calls. Finding a `bwrap` executable does not establish that isolation works: the kernel may disable user namespaces. Failures usually involve user namespaces or system security policies; use a Linux / WSL environment that supports the required isolation. Python execution uses `/usr/bin/python3`; C, C++ and Java use system compilers visible inside the sandbox, independently of custom compilers in your virtual environment.

## 4. Submit a real request

Install browser dependencies before platform delivery:

```bash
npm ci
```

Install Chrome and sign in to Educoder with your own teacher account in the browser opened by the import adapter. Its session is stored locally in `.browser-profile/`. Your everyday Chrome session may use a different profile, so the first use requires signing in. For a browser running outside WSL, see “Browser source reading” below.

Open <http://127.0.0.1:8765/> and enter the course scope, question types and counts, the classroom's full online-exam list URL and the course name already present on the platform. For platform delivery, clear “仅本地生成” (local generation only). The application saves an unpublished exam, configures questions and programming cases, and reads them back for verification. The teacher then publishes the exam on the platform.

For file export only, select “仅本地生成”; platform targets and login are unnecessary. Upload a text-based PDF or DOCX when you want course materials to define the scope. Uploading materials does not guarantee coverage of every knowledge point; teachers should review the result.

You can also submit a platform-delivery task through the local API. Replace the classroom placeholder and course name with your own:

```bash
curl -sS http://127.0.0.1:8765/api/agent-start \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Create an assignment on sorting algorithms with 2 multiple-choice, 2 true/false and 2 fill-in-the-blank questions.","execute":true,"classroom_url":"https://www.educoder.net/classrooms/<classroom-id>/exercise","course":"Your course name"}'
```

Pass `"execute": true` explicitly for platform delivery. For local generation, pass `"execute": false` and omit `classroom_url` and `course` if desired.

After receiving the task ID, follow progress in the interface. `GET /api/agent-tasks/<id>` returns the result, and `GET /api/agent-events` provides SSE events. Download Excel, JSON and programming assessment packages from the completed task card. Teacher packages contain answers and hidden cases and should remain with the teacher. The fixed `demo.py` export is independent of current interface tasks and is labeled as a fixed demonstration.

## 5. Optional capabilities

**Vector retrieval:**

```bash
python -m pip install -r requirements-retrieval.txt
python -m scripts.index_corpus --vectors --download-model
```

Vector retrieval and RRF augment BM25 after you explicitly download local model weights. The application does not download them during task execution; missing dependencies or weights cause an explicit fallback to BM25. Course text is sent to your configured inference service. Local embeddings do not use a remote embedding API.

**Browser source reading:**

```bash
npm ci
```

With Chrome installed, failed HTTP reads can fall back to a read-only browser. Without Node / Chrome, access failures remain visible and ordinary HTTP retrieval remains available. To use Windows Chrome from WSL, explicitly set `EDUCODER_BROWSER_NODE` to the WSL path of Windows `node.exe`, and `EDUCODER_PLAYWRIGHT_MODULE` to a Playwright directory resolvable by that Windows Node installation. Otherwise, the application uses Node from PATH and the project dependencies. The optional `EDUCODER_SOURCE_CDP_URL` accepts only local debugging endpoints.

**Structured search:** Set `EDUCODER_TAVILY_API_KEY` to enable it. Otherwise, the existing public search paths are used. Public source services may rate-limit or reject access.

**Local generation only:** Select the corresponding interface option or set `execute=false` in the API to export files without platform delivery. Fixed offline demos and CI use local execution or mocks and require no platform account. Browser and login setup is described in the previous section. The repository contains no real classroom URLs or sessions; upstream page or permission changes may require adapter updates.

## 6. Troubleshooting

| Symptom | Action |
| --- | --- |
| The interface opens, but tasks do not run | Use `bash start.sh` to start both the API and Worker |
| The port is occupied | Choose another port with `bash start.sh --port 8877` |
| Model connection fails | Run `python -m scripts.check_model_connection --check-only`; check the URL, permissions, balance and rate-limit information |
| Programming verification is unavailable | Run `python -m scripts.doctor --programming`; check bubblewrap, system compilers and user namespace support |
| Retrieval uses only BM25 | This is the expected fallback without vector dependencies or local weights; see the configuration above |
| Text cannot be extracted from a scanned PDF | Use a text-based PDF or DOCX; direct PPT input and formulas stored as images have limited support |

For tasks needing attention, inspect the failed stage and retained results in the interface, correct the configuration and continue the existing task. Local output lives in `outputs/` and includes reference answers and hidden data that teachers should keep private.
