# Kế hoạch thực hiện và đối chiếu thang điểm

## 1. Việc phải làm (những gì mã nguồn chưa thể tự làm)
Thứ tự theo độ khẩn: nút thắt là **thu thập đủ 5-10 phiên dữ liệu thật**, nên bước 1-3 làm ngay.

| # | Việc | Ghi chú |
|---|---|---|
| 1 | Có khóa NEO API, đăng ký IP của máy chạy thu thập | Đề nêu có kiểm soát IP đã đăng ký; dùng một máy cố định cho cả giai đoạn thu thập |
| 2 | Đọc tài liệu NEO, điền `config/neo_connection.yaml` | Xác thực, tin nhắn đăng ký, giới hạn số mã mỗi kết nối |
| 3 | Chạy `probe_neo.py record` một phiên, rồi `analyze` | Biết tên trường, tần suất, độ trễ, có/không nước ngoài-room-3 mức |
| 4 | Điền `config/neo_field_map.yaml`, thử `run_collector --source neo` ngắn | So với bảng giá thật |
| 5 | Chạy thu thập từ trước 09:00 suốt các phiên; mỗi phiên `freeze_picks` | ≥ 5 phiên (ưu tiên 10); phiên đầu dùng hiệu chỉnh ngưỡng |
| 6 | Đối chiếu phí, giờ giao dịch, bước giá; sửa `screener.yaml` | Ghi nguồn đối chiếu vào báo cáo |
| 7 | Nếu NEO thiếu lịch sử cho ADV/RVOL: lấy bổ trợ từ SSI FastConnect | Ghi rõ nguồn; hoặc dùng ít phiên và nêu giới hạn |
| 8 | Hoàn thành mục B của `TEST_PLAN.md`, chụp ảnh màn hình, quay video demo | Video không để lộ token/IP/tài khoản |
| 9 | Viết báo cáo theo `report/BAO_CAO_KHUNG.md` (8-12 trang) | Dùng dữ liệu thật, không dùng mô phỏng làm bằng chứng |
| 10 | Đóng gói: `MSSV_HoTen_NEOAPI_FinTech.zip` (không có `.env`, không có `data/*.db` chứa dữ liệu nhạy cảm), `MSSV_HoTen_BaoCao.pdf/docx`, `MSSV_HoTen_Demo.mp4` | Theo quy cách đặt tên của đề |

Nếu **không thể** có khóa/dữ liệu thật kịp hạn: sản phẩm vẫn chạy được ở chế độ mô phỏng, nhưng đề giới hạn điểm khi NEO API không phải thành phần
cốt lõi (≤ 50/100). Vì vậy phải xin giảng viên hướng dẫn sớm nếu có trở ngại về khóa.

## 2. Đối chiếu tiêu chí chấm (100 điểm)
| Tiêu chí | Điểm | Hạng mục đáp ứng | Bằng chứng nộp |
|---|---|---|---|
| 1. Vấn đề và giá trị | 15 | Bộ lọc nhận biết chi phí ở quy mô vốn người dùng (`THIET_KE.md` §1) | Báo cáo mục 2; demo thay đổi vốn → thứ hạng đổi |
| 2. Khai thác NEO API, kỹ thuật dữ liệu | 20 | WebSocket có lưu trữ; ≥ 3 trường (giá, sổ lệnh 3 mức, KL, nước ngoài, room); múi giờ UTC+7; kiểm tra chất lượng; token bucket 5 req/s; tái lập qua README | `probe_neo` log, bảng `quality_log`, từ điển dữ liệu |
| 3. Phương pháp tài chính, chiều sâu | 20 | Chi phí thực thi duyệt sổ lệnh; yếu tố có lý luận; ngưỡng từ phân phối; độ nhạy; forward-test không nhìn trước | `METHODS.md`, kết quả độ nhạy và forward-test |
| 4. Chất lượng kỹ thuật | 20 | Mô-đun hóa (neo_api/data/finance/analytics/app); log, xử lý lỗi; `.env.example`; 46 test | Cấu trúc mã, `pytest` |
| 5. Sản phẩm và trải nghiệm | 10 | 5 tab; đủ yêu cầu giao diện Mục 6; trạng thái rỗng/lỗi | Ảnh chụp, video |
| 6. Kiểm thử, kiểm chứng | 10 | `TEST_PLAN.md` A + B; báo cáo hạn chế trung thực | Bảng kết quả mục B |
| 7. Tài liệu, báo cáo, trình bày | 5 | README, báo cáo, video; trích nguồn | Tệp nộp |

**Tránh các mức trần điểm:** có sản phẩm chạy và video (không bị ≤ 60); NEO là cốt lõi (không bị ≤ 50); có lớp logic tài chính (không bị giới hạn
tiêu chí 3, 5); không lộ khóa (`.gitignore`, `.env.example`, kiểm tra lịch sử commit); không có hàm đặt lệnh.

## 3. Khác biệt với các hướng phổ biến và liêm chính học thuật
- Bộ lọc nhiều yếu tố (OBI/RVOL/dòng tiền nước ngoài/động lượng) là hướng nhiều bạn sẽ chọn, kể cả một kho mã công khai đã thấy. Giá trị khác biệt của
  bài là **A (chi phí thực thi theo vốn)** và **B (kiểm chứng bất biến)**, cùng cách chuẩn hóa/chấm điểm khác. Nên giữ A, B là trụ cột khi trình bày.
- Mã trong gói này do trợ lý AI viết theo yêu cầu của bạn. Đề cho phép dùng AI nhưng bạn **phải hiểu và giải thích được mọi phần** khi bảo vệ (Mục 13).
  Gợi ý: tự đọc từng module theo thứ tự `finance/execution.py` → `analytics/features.py` → `scoring.py` → `forward_test.py`, tự chạy test, tự đổi một tham số và dự đoán kết quả
  trước khi chạy. Nêu việc dùng công cụ AI trong báo cáo theo quy định học phần.
- Không sao chép mã hay câu chữ từ bài của bạn khác. Giữ lịch sử commit để chứng minh quá trình.

## 4. Gợi ý lịch (điều chỉnh theo hạn nộp thực tế - hiện chưa biết)
| Giai đoạn | Việc |
|---|---|
| Ngày 0-1 | Khóa API, IP, probe, điền ánh xạ trường |
| Ngày 1-2 | Chạy thu thập thử, đối chiếu bảng giá; sửa lỗi kết nối |
| Ngày 2-12 | Thu thập thật mỗi phiên; mỗi phiên chốt picks; song song hoàn thiện giao diện/báo cáo/đối chiếu |
| Ngày cuối | Đánh giá forward-test, độ nhạy, ảnh chụp, video, đóng gói, kiểm tra rò rỉ khóa |
