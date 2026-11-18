# ExecScreen - Bộ lọc cổ phiếu theo quy mô vốn

Đồ án cá nhân cuối kỳ - *Gói phần mềm ứng dụng cho tài chính 1* (NEO API).
**Công cụ phân tích học thuật, không phải khuyến nghị đầu tư. Không đặt/sửa/hủy lệnh thật.**

## Ý tưởng một câu
Bộ lọc cổ phiếu thông thường xếp hạng theo tín hiệu giá/khối lượng. ExecScreen xếp hạng theo tín hiệu
**sau khi trừ chi phí thực thi ở đúng số vốn của bạn** (duyệt sổ lệnh 3 mức → trượt giá, độ phủ, chi phí vòng),
và **tự kiểm chứng** bộ lọc bằng forward-test giả lập có chốt danh sách bất biến.

## Trạng thái hiện tại (đọc kỹ)
| Phần | Trạng thái |
|---|---|
| Lõi tài chính, chấm điểm, forward-test, lưu trữ, kiểm tra chất lượng, giao diện | Đã viết, **46 test tự động qua**, chạy được trên dữ liệu **mô phỏng** |
| Kết nối NEO thật (`neo_api/stream.py`, `client.py`) | Đã viết khung (kết nối lại, giới hạn tần suất, xử lý lỗi) nhưng **chưa thử với máy chủ thật** |
| Ánh xạ trường NEO (`config/neo_field_map.yaml`), thông số kết nối (`config/neo_connection.yaml`) | **Chưa điền** - phải làm sau khi chạy `scripts/probe_neo.py` với khóa thật |
| Phí, giờ giao dịch, bước giá | Giá trị mặc định cần **đối chiếu** quy định/biểu phí hiện hành |
| Dữ liệu thật nhiều phiên, kết quả forward-test thật | **Chưa có** - phải tự thu thập (xem `docs/KE_HOACH.md`) |

Dữ liệu mô phỏng (`source = mock`) luôn bị giao diện cảnh báo đỏ; **không dùng làm bằng chứng trong báo cáo**.

## Cài đặt
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # rồi điền khóa thật (không commit .env)
pytest                                                 # 46 test
```

## Chạy thử nhanh với dữ liệu mô phỏng
```bash
python scripts/make_demo_data.py --db data/execscreen.db --days 10 --interval 30
python main.py
```
Ứng dụng FastAPI sẽ tự mở trình duyệt tại `http://127.0.0.1:8000/`. Dừng máy chủ bằng `Ctrl+C`.
Nếu chưa có CSDL, trang chủ có nút **Tạo dữ liệu mô phỏng**.

## Quy trình với NEO API thật
1. Điền `.env` (`NEO_ACCESS_TOKEN`, `NEO_WS_URL`, `NEO_REST_BASE_URL`); đăng ký IP của máy chạy thu thập.
2. Điền `config/neo_connection.yaml` (xác thực, tin nhắn đăng ký) theo tài liệu NEO.
3. `python scripts/probe_neo.py record --seconds 300` trong giờ giao dịch, rồi
   `python scripts/probe_neo.py analyze data/raw/probe.jsonl --ts-field <...> --symbol-field <...>`
   → biết tên trường, tần suất, độ trễ, có/không có nước ngoài và room.
4. Điền `config/neo_field_map.yaml` theo kết quả bước 3.
5. Chạy `python scripts/run_collector.py --source neo --db data/execscreen.db` từ trước 09:00, suốt các phiên.
6. Mỗi phiên tại giờ quyết định: `python scripts/freeze_picks.py --date YYYY-MM-DD`.
7. Sau ≥ 1 phiên: `python scripts/evaluate_forward.py`; xem giao diện.

## Cấu trúc
```
config/        screener.yaml (mọi tham số), universe_sample.csv, neo_*.yaml (cần điền)
src/execscreen/
  neo_api/     auth, ratelimit (5 req/s), field_map (+gộp tin từng phần), stream (WebSocket), client (REST)
  data/        storage (SQLite WAL), quality (kiểm tra), collector (+lấy mẫu), mock (dữ liệu mô phỏng)
  finance/     ticks, fees, microstructure (spread, OBI), execution (duyệt sổ lệnh = phương án A)
  analytics/   features, scoring, sensitivity, forward_test (= phương án B), pipeline
  ai/          nl_to_config (tùy chọn; kiểm schema; mặc định tắt)
  app/         main.py (FastAPI + Jinja2), templates/index.html, charts.py
main.py         launcher mở trình duyệt
scripts/       probe_neo, run_collector, make_demo_data, freeze_picks, evaluate_forward
tests/         46 test (công thức tính tay, chống nhìn trước, bất biến picks, chất lượng dữ liệu, giao diện)
docs/          THIET_KE, METHODS, DATA_DICTIONARY, TEST_PLAN, KE_HOACH, kien_truc.png
report/        BAO_CAO_KHUNG.md
```

## Giới hạn đã biết
Chỉ thấy 3 mức giá; không thấy lệnh ẩn; không mô hình hóa tác động của chính lệnh lên giá; vốn vượt độ sâu
chỉ gắn cờ; trọng số là tiên nghiệm chưa tối ưu; mẫu forward-test nhỏ nên không kết luận thống kê.
Chi tiết trong `docs/METHODS.md` mục 8.
