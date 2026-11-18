# Kế hoạch kiểm thử và kiểm chứng

## A. Kiểm thử tự động (`pytest`, 46 test, ~9 giây)
| Nhóm | Test tiêu biểu | Điều được kiểm chứng |
|---|---|---|
| Công thức tính tay | `test_walk_book_buy_two_levels_hand_calc`: Q = 100 triệu, ask 50.000×1.000 + 50.100×2.000, mid 49.950 → VWAP 50.050, trượt giá 20,02 bps, độ phủ 4× | Duyệt sổ lệnh đúng |
| Biên | vượt độ sâu → `PARTIAL` (không ngoại suy); vốn < 1 lô → `TOO_SMALL`; sổ rỗng/chéo → NaN | Không đoán khi thiếu dữ liệu |
| Nhất quán | `cost_table` (vector hóa) khớp `walk_book` (đơn); chi phí vòng = trượt giá hai chiều + phí + thuế | Hai cài đặt cho cùng kết quả |
| Vi cấu trúc | OBI, spread, mid, Parkinson, bước giá, biên độ, làm tròn lô | Công thức đúng |
| Chấm điểm | bộ lọc cứng và lý do; yếu tố thiếu → chuẩn hóa lại trọng số; đóng góp cộng đúng bằng điểm; λ đổi thứ hạng; ngưỡng cố định được dùng | Logic xếp hạng |
| **Chống nhìn trước** | `test_no_lookahead`: thêm/đầu độc dữ liệu có ts > as_of không làm đổi yếu tố; `test_calibration_uses_only_calibration_sessions` | Không rò rỉ tương lai |
| Forward-test | tính tay lợi suất ròng (mua 50.000, bán 51.000, phí 15/15 + thuế 10 bps); `picks` bất biến (UPDATE/DELETE bị chặn, chốt lại bị từ chối); PENDING khi chưa có phiên sau; lợi suất ròng < giữa-sang-giữa vì có chi phí | Quy trình B đúng và trung thực |
| Chất lượng dữ liệu | trùng, đảo thứ tự, giảm cộng dồn, sổ chéo, ngoài biên, âm, thiếu mã, tương lai; cờ NO_QUOTE/NONCONT/LATE | Xử lý lỗi dữ liệu |
| Thu thập | luồng bị ngắt → trạng thái `connected=false` + `last_error`; bản ghi trùng bị đếm/bỏ; lấy mẫu giữ snapshot cuối khoảng | Chịu lỗi, không treo |
| Kết nối | giới hạn 5 req/s (10 yêu cầu sau 5 token đầu phải chờ đúng 2,0 giây); lùi lũy tiến; tin lỗi không làm sập; hết hạn JWT; ánh xạ trường + gộp tin từng phần | Hạ tầng NEO |
| AI | đầu ra ngoài schema (khóa lạ, trọng số vượt khoảng, lệnh "mua VNM") bị từ chối; cấu hình gốc không bị sửa | Rào chắn an toàn |
| Giao diện | `AppTest` chạy headless: không ngoại lệ, đủ 5 tab, cảnh báo dữ liệu mô phỏng, trạng thái không có CSDL | Sản phẩm chạy được, xử lý trạng thái rỗng |

Lỗi thật đã được test phát hiện khi phát triển (ghi lại trong báo cáo như bằng chứng quy trình kiểm thử): xếp hạng lỗi khi không mã nào đủ điều kiện;
ghi CSDL lỗi kiểu thời gian; bộ giới hạn tần suất lặp vô hạn do sai số số thực.

## B. Kiểm chứng bằng dữ liệu thật (BẮT BUỘC làm khi có khóa; điền kết quả vào báo cáo)
| # | Việc | Cách làm | Tiêu chí đạt | Kết quả (điền) |
|---|---|---|---|---|
| 1 | Đối chiếu snapshot với bảng giá thật | Chụp màn hình bảng giá NEO Invest tại 5 thời điểm × 5 mã, so với DB | Giá, KL 3 mức khớp (sai lệch do độ trễ nêu rõ) | |
| 2 | Đối chiếu cộng dồn cuối ngày | So `cum_volume`/`cum_value` cuối phiên với số liệu sàn/REST | Sai lệch < 0,5% | |
| 3 | Độ trễ | `probe_neo.py analyze --ts-field ...` | Báo cáo P50/P95; `entry_delay_seconds` ≥ P95 | |
| 4 | Tần suất tin | `probe_neo.py analyze` | Biết tin/giây/mã; chu kỳ lấy mẫu hợp lý | |
| 5 | Mất kết nối | Rút mạng 60 giây khi đang chạy | Tự kết nối lại; ghi nhận khoảng trống; giao diện báo "đã dừng" | |
| 6 | Token hết hạn / sai | Dùng token sai | Lỗi rõ ràng, không lộ token trong log | |
| 7 | Giới hạn tần suất | Gọi REST dồn dập có chủ đích (trong giới hạn) | Không vượt 5 req/s | |
| 8 | Có/không có nước ngoài và room | `probe_neo.py` | Quyết định bật/tắt `foreign_net` | |
| 9 | Chi phí thực thi vs thực tế | Với 3 mã, tự ước tính "nếu mua X triệu" từ bảng giá thật tại 3 thời điểm, so với `walk_book` | Khớp trong dung sai làm tròn | |
| 10 | Độ nhạy trọng số | `weight_sensitivity` trên dữ liệu thật | Báo cáo Spearman và trùng top-N | |
| 11 | Forward-test | 5-10 phiên, `freeze_picks` mỗi phiên, `evaluate_forward` | Báo cáo kết quả trung thực kèm khoảng tin cậy, kể cả khi không có lợi thế | |
| 12 | Kiểm tra rò rỉ khóa | `git grep -nE "(token|secret|password)"`; xem lịch sử commit | Không có giá trị thật | |

## C. Dữ liệu mô phỏng
Chỉ phục vụ phát triển và kiểm thử. Kết quả trên dữ liệu mô phỏng **không được** trình bày như kết quả thị trường. Trong báo cáo, nếu
có đưa ví dụ từ dữ liệu mô phỏng thì phải ghi chú rõ (đề Mục 13: không dùng dữ liệu giả để tạo kết quả đẹp mà không công bố).
