# Personal AI Team

Personal AI Team là bộ khung local để nối các AI CLI mà chính người dùng lựa chọn. Repo không bật sẵn Codex, Antigravity, Ollama hay route nào. Người dùng khai báo CLI trong YAML, đặt ID tùy ý, rồi chạy agent riêng lẻ hoặc phối hợp qua route.

## Cài đặt

Yêu cầu Python 3.10 trở lên và các CLI agent mà bạn tự chọn.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Thêm agent đầu tiên

Mở `config/agents.yaml` và khai báo ID, tên hiển thị cùng CLI. Ví dụ CLI giả định tên `my-ai-cli` nhận prompt qua tham số `--prompt`:

```yaml
version: 1
agents:
  assistant:
    name: My Assistant
    enabled: true
    adapter: command
    command: my-ai-cli
    args: ["--prompt", "{prompt}"]
    prompt_mode: argument
    version_args: ["--version"]

settings:
  require_human_approval: true
  auto_commit: false
  auto_merge: false
```

Đổi `command` và `args` theo CLI bạn cài. Agent ID như `assistant` là tên nội bộ, dùng trong lệnh và route. Các phần tử trong `args` là danh sách đối số riêng biệt; chương trình không chạy chúng qua shell. Placeholder `{prompt}`, `{agent}` và `{project_root}` được thay bằng nội dung tương ứng. Nếu CLI đọc prompt từ stdin, bỏ `{prompt}` khỏi `args` và đặt `prompt_mode: stdin`; cách này cũng phù hợp hơn với prompt dài.

Có thể bắt đầu từ [config/agents.example.yaml](config/agents.example.yaml). Các adapter tích hợp sẵn `codex`, `antigravity`, `ollama` vẫn dùng được khi người dùng khai báo rõ `adapter` tương ứng; chúng không được bật mặc định.

Ví dụ khai báo các adapter chuyên biệt này (chỉ thêm cái bạn dùng):

```yaml
agents:
  my_codex:
    name: Codex CLI
    enabled: true
    adapter: codex
    command: codex

  my_antigravity:
    name: Antigravity CLI
    enabled: true
    adapter: antigravity
    command: agy

  my_local_model:
    name: Local model
    enabled: true
    adapter: ollama
    command: ollama
    model: llama3.2
```

Kiểm tra agent đã cài và cấu hình:

```powershell
python -m orchestrator.main doctor
```

## Chạy agent

Chạy agent vừa khai báo:

```powershell
python -m orchestrator.main run "Phân tích cấu trúc dự án" --agent assistant
```

Nếu chỉ có một agent, có thể bỏ `--agent`. Mở menu nhập yêu cầu nhiều dòng bằng:

```powershell
python -m orchestrator.main
```

Adapter tổng quát yêu cầu CLI trả về một JSON object theo [schemas/agent_result.schema.json](schemas/agent_result.schema.json). Prompt hướng dẫn agent tạo đúng định dạng này, bao gồm `task_id` và `agent`. Điều này cho phép orchestrator kiểm tra, lưu kết quả và resume công việc nhất quán. CLI chỉ trả lời văn bản tự do cần được bọc bằng script nhỏ do người dùng cấu hình, hoặc dùng một trong các adapter chuyên biệt có sẵn.

## Thêm agent và route

Khai báo mỗi agent bằng ID riêng trong `config/agents.yaml`. Dùng [config/routing.example.yaml](config/routing.example.yaml) làm mẫu. Để phối hợp nhiều agent, thêm route vào `config/routing.yaml`:

```yaml
version: 1
routing:
  ask_and_review:
    primary: assistant
    reviewer: reviewer
    require_review: true
    execution: sequential

execution:
  mode: sequential
  allow_parallel: true
  max_agents_per_task: 4
  max_retries: 1
```

Trong ví dụ, `reviewer` cũng phải được khai báo và bật trong `agents.yaml`. Agent review chạy sau và nhận kết quả trước đó. Dùng `execution: either` nếu muốn chọn tuần tự hoặc song song khi chạy lệnh. Chạy song song phù hợp với các agent trả lời độc lập; mỗi agent nhận cùng yêu cầu gốc.

Chạy route hoặc nhiều agent:

```powershell
python -m orchestrator.main run "Đánh giá thiết kế này" --route ask_and_review
python -m orchestrator.main run "So sánh hai phương án" --agent all --parallel
```

Các lần gọi lại tối đa được điều khiển bằng `max_retries` (số lần thêm sau lần đầu). Giới hạn agent cho mỗi workflow nằm tại `execution.max_agents_per_task`.

## Báo cáo, trạng thái và phục hồi

Khi chạy nhiều agent, nếu không chỉ định agent tổng hợp, ứng dụng ghép kết quả đã kiểm định thành báo cáo Markdown. Muốn một agent tạo báo cáo tổng hợp bằng AI, đặt ID đó trong `settings.synthesis_agent` ở `config/agents.yaml`.

```powershell
python -m orchestrator.main status
python -m orchestrator.main status WF-202611120001 --show-task
python -m orchestrator.main resume WF-202611120001
```

Trạng thái workflow nằm trong `state/workflows/`; kết quả agent và báo cáo ở `results/`; log ở `logs/`. Các thư mục này bị Git ignore. `status` ẩn task text mặc định. Dữ liệu vẫn lưu dạng văn bản cục bộ cho đến khi được dọn.

Xem trước dữ liệu workflow cũ trước khi xóa:

```powershell
python -m orchestrator.main prune --older-than-days 30
```

Chỉ thêm `--apply` sau khi đã xem danh sách cần dọn.

## Cấu hình và an toàn

- `config/agents.yaml`: agent, command, đối số và agent tổng hợp tùy chọn.
- `config/routing.yaml`: route, thứ tự, chế độ thực thi, retry và giới hạn agent.
- `config/policies.yaml`: timeout, lọc tệp/ngữ cảnh và tùy chọn log.

Khi prompt nhắc đường dẫn tệp trong workspace, orchestrator có thể đưa nội dung vào ngữ cảnh. Có giới hạn kích thước, lọc tên tệp nhạy cảm và quét heuristic một số mẫu secret phổ biến. Bộ lọc không thể nhận ra mọi định dạng bí mật. Đọc `config/policies.yaml` trước khi dùng với dữ liệu riêng tư.

## Kiểm thử

```powershell
python -m unittest discover -s tests -v
```

GitHub Actions chạy test trên Windows, macOS và Ubuntu với Python 3.10–3.12.
