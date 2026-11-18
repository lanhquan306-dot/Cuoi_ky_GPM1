# Khung báo cáo cuối kỳ (8-12 trang A4, không tính phụ lục)

Tên tệp nộp: `MSSV_HoTen_BaoCao.pdf/docx`. Viết bằng lời của bạn; các ô `[điền]` phải thay bằng dữ liệu thật.
Không đưa token, IP, dữ liệu tài khoản vào báo cáo/ảnh chụp.

| Phần | Độ dài | Nội dung cần viết | Lấy từ đâu |
|---|---|---|---|
| **1. Tóm tắt điều hành** | ½ trang | Vấn đề (chi phí thực thi bị bỏ qua), người dùng, giải pháp (bộ lọc + chi phí theo vốn + forward-test), dữ liệu NEO dùng `[điền: kênh/trường]`, phương pháp, kết quả chính `[điền]`, hạn chế lớn nhất | Cuối cùng khi đã có kết quả |
| **2. Vấn đề và nhu cầu người dùng** | 1 trang | Bối cảnh thị trường vốn VN, khó khăn của nhà đầu tư cá nhân, ví dụ một mã tín hiệu đẹp nhưng chi phí cao `[điền ví dụ thật từ dữ liệu]`, giá trị kỳ vọng | `THIET_KE.md` §1 |
| **3. Thiết kế sản phẩm** | 1,5 trang | Sơ đồ kiến trúc (`docs/kien_truc.png`) và nhiệm vụ từng lớp; luồng dữ liệu; lý do công nghệ; lý do không dùng ML | `THIET_KE.md` §2, §5 |
| **4. Dữ liệu NEO API** | 1,5 trang | Kênh/endpoint thực dùng `[điền theo probe]`; trường, tần suất tin `[điền]`, chu kỳ lấy mẫu; lưu trữ, làm sạch (bảng sự cố từ `quality_log`); độ phủ dữ liệu; từ điển dữ liệu tóm tắt; giới hạn 5 req/s | `DATA_DICTIONARY.md`, kết quả `probe_neo`, tab Chất lượng dữ liệu |
| **5. Phương pháp tài chính/phân tích** | 2 trang | Công thức từng yếu tố và lý do; duyệt sổ lệnh và định nghĩa chi phí; bộ lọc cứng; điểm ròng; cơ sở ngưỡng; độ nhạy | `METHODS.md` §1-5 |
| **6. Triển khai sản phẩm** | 1 trang | Ảnh chụp 5 tab; quy trình sử dụng; trạng thái lỗi/không dữ liệu | Ảnh chụp thật (không phải dữ liệu mô phỏng) |
| **7. Kiểm thử và kết quả** | 1,5-2 trang | Bảng kiểm thử tự động; bảng đối chiếu dữ liệu thật (TEST_PLAN mục B); kết quả forward-test kèm khoảng tin cậy và rổ ngẫu nhiên; độ nhạy; các lỗi đã gặp và đã sửa | `TEST_PLAN.md`, `evaluate_forward.py` |
| **8. Hạn chế và sử dụng có trách nhiệm** | ½-1 trang | Giới hạn dữ liệu (3 mức, độ trễ), giới hạn mô hình, mẫu nhỏ, rủi ro diễn giải; bảo mật; sản phẩm **không** dùng để: khuyến nghị đầu tư, tự động giao dịch, thao túng giá | `METHODS.md` §8 |
| **9. Hướng phát triển** | ¼ trang | Thêm mức sổ lệnh sâu hơn, dữ liệu nhiều tháng, hiệu chỉnh trọng số ngoài mẫu, mô hình tác động giá, cảnh báo, điều chỉnh quyền | |
| **10. Kết luận** | ¼ trang | Giá trị tạo ra, bài học kỹ thuật và tài chính | |
| **Phụ lục** | không giới hạn | Từ điển dữ liệu đầy đủ, công thức chi tiết, kết quả test, hướng dẫn cài đặt, đường dẫn mã/video, **khai báo việc dùng công cụ AI** | |

## Danh sách kiểm trước khi nộp
- [ ] Tất cả số liệu trong báo cáo là dữ liệu thật hoặc được ghi rõ là mô phỏng.
- [ ] Mỗi con số trong mục 7 truy được tới lệnh/tệp tạo ra nó (tính tái lập).
- [ ] Kết luận forward-test không vượt quá bằng chứng (mẫu nhỏ, không tuyên bố lợi nhuận).
- [ ] Có dòng: "Công cụ phân tích học thuật, không phải khuyến nghị đầu tư".
- [ ] Trích nguồn: tài liệu NEO, SSI (nếu dùng), các bài học thuật ở `METHODS.md` §9.
- [ ] Không lộ token/IP/tài khoản trong mã, báo cáo, ảnh, video, lịch sử git.
- [ ] Giải thích được mọi module khi bảo vệ.
