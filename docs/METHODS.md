# Phương pháp tài chính và phân tích

Ký hiệu: giá VND; bps = 0,01%; "phiên liên tục" là các khung khớp lệnh liên tục (không gồm ATO/ATC/nghỉ trưa).
Giá trị mặc định nằm trong `config/screener.yaml` và là **giả định khởi điểm có lý luận**, chưa tối ưu trên dữ liệu.

## 1. Chỉ số vi cấu trúc
- Giá giữa `mid = (bid1 + ask1)/2`; chỉ tính khi `0 < bid1 < ask1` (sổ không chéo, có cả hai phía).
- Spread (bps) `= (ask1 − bid1)/mid × 10⁴`.
- Mất cân bằng sổ lệnh `OBI = (ΣBid₁₋₃ − ΣAsk₁₋₃)/(ΣBid₁₋₃ + ΣAsk₁₋₃) ∈ [−1, 1]`. Chỉ có 3 mức nên chỉ phản ánh áp lực gần giá.
  OBI dùng trong yếu tố là **trung bình các snapshot trong cửa sổ** (mặc định 10 phút, cần ≥ 3 snapshot) để giảm nhiễu.
- Biến động Parkinson (dùng cho mô hình tác động tùy chọn): `σ = ln(H/L)/(2√ln2)`.

## 2. Phương án A - chi phí thực thi (duyệt sổ lệnh)
Với vốn danh nghĩa Q: số cổ phiếu mục tiêu `N = ⌊Q / giá_tốt_nhất / 100⌋ × 100`.
Duyệt các mức từ tốt đến xấu (mua: ask1→ask3; bán: bid1→bid3) đến khi đủ N hoặc hết 3 mức.

```
VWAP        = Σ(giá_i × KL_khớp_i) / Σ KL_khớp_i
slip_mua    = (VWAP / mid − 1) × 10⁴          slip_bán = (1 − VWAP / mid) × 10⁴
độ phủ      = Σ KL_hiển_thị / N
vượt độ sâu = KL_khớp < N
chi phí vòng= slip_mua + slip_bán + phí_mua + phí_bán + thuế_bán
```
Trượt giá đã chứa nửa spread mỗi chiều nên **không cộng spread lần nữa**.

Trong cửa sổ lookback (mặc định 30 phút, phiên liên tục, ≥ 10 snapshot hợp lệ) lấy **trung vị (P50) và phân vị 90 (P90)**
của chi phí vòng; P90 dùng để lọc/phạt vì rủi ro nằm ở các thời điểm sổ mỏng, không ở trạng thái trung bình.
Tỷ lệ `beyond_share` = phần snapshot mà lệnh vượt độ sâu 3 mức.

**Không ngoại suy ngầm.** Nếu `beyond_depth: sqrt_impact`, phần chưa khớp được cộng một ước lượng tác động căn bậc hai
`Y · σ · √(giá_trị_chưa_khớp / ADV) × tỷ_lệ_chưa_khớp` (Almgren et al.), với Y là tham số giả định - phải nêu rõ khi báo cáo.
Mặc định chỉ gắn cờ.

Tham số tham chiếu: tỷ lệ tham gia `Q/ADV` (ADV = GTGD trung bình ngày, tối đa 20 phiên trước) bị chặn ở 5% (quy ước thực hành;
đổi được); phí/thuế lấy theo cấu hình (phải đối chiếu biểu phí VPBankS; thuế bán 0,1%).

## 3. Yếu tố của bộ lọc
| Yếu tố | Công thức | Lý do |
|---|---|---|
| `mom_ref` | `last/ref − 1` | Động lượng trong phiên so với giá tham chiếu |
| `range_pos` | `(last − low)/(high − low)` | Vị trí trong biên độ ngày: giá đóng gần đỉnh cho thấy lực mua giữ được |
| `rvol_tod` | `KL_cộng_dồn_hiện_tại / TB(KL_cộng_dồn cùng giờ, ≤ 20 phiên trước)`; cần ≥ 3 phiên | Khối lượng bất thường **so với cùng khung giờ**, vì khối lượng trong ngày có dạng chữ U |
| `obi3` | OBI trung bình cửa sổ | Áp lực cung/cầu gần giá |
| `range_pct` | `(high − low)/ref` | Mức hoạt động/biến động trong ngày (trọng số 0,5; đổi dấu được) |
| `foreign_net` | `(mua NN − bán NN)/GTGD`; nếu thiếu: `−Δroom × giá / GTGD` (ghi `foreign_src = room_proxy`) | Dòng tiền nước ngoài; **mặc định tắt**, chỉ bật khi xác nhận dữ liệu |

Yếu tố thiếu dữ liệu (NaN) **không bị thay bằng 0**: trọng số được chuẩn hóa lại trên các yếu tố còn có; mã có < 2 yếu tố bị loại (`FEW_FACTORS`).

## 4. Chấm điểm
1. **Chuẩn hóa chéo mã**: winsorize 2%/98% rồi z-score (hoặc hạng phần trăm); nhân `direction`.
2. **Điểm yếu tố** `S = Σ wᵢ zᵢ / Σ wᵢ` (trên yếu tố có dữ liệu). Đóng góp từng yếu tố = `wᵢ zᵢ / Σ wᵢ` → cộng lại đúng bằng `S` (được kiểm thử).
3. **Bộ lọc cứng** (áp trước khi xếp hạng): có chào mua/bán hợp lệ và đủ snapshot; không khóa trần/sàn; dữ liệu không cũ;
   `Q/ADV ≤ 5%`; chi phí vòng P90 ≤ ngưỡng; `beyond_share ≤ 50%`.
4. **Điểm ròng** `= z(S) − λ · z(chi phí P90)` trên tập đủ điều kiện (λ mặc định 0,5). Điểm 0-100 = hạng phần trăm của điểm ròng.

**Cơ sở của ngưỡng.** Ngưỡng chi phí P90 lấy theo phân vị (mặc định 80%) của phân phối trong rổ, và **được cố định từ các
phiên hiệu chỉnh** (mặc định 4 phiên đầu) rồi áp nguyên cho các phiên kiểm tra, để tránh dùng thông tin của chính phiên đang đánh giá.
Các ngưỡng quy ước (5% ADV, 50% snapshot) là quy tắc thực hành, có thể đổi trong cấu hình và nên được báo cáo kèm phân tích độ nhạy.

## 5. Độ nhạy
`analytics/sensitivity.py`: 200 lần nhiễu trọng số ±30% (ngưỡng giữ cố định) → tương quan hạng Spearman với xếp hạng gốc,
tỷ lệ trùng top-N, tần suất mỗi mã nằm trong top-N. Nếu thứ hạng rất nhạy, **không diễn giải mạnh thứ tự chính xác**.

## 6. Forward-test (phương án B)
1. Tại giờ quyết định `t₀` (mặc định 10:00) chốt vào bảng `picks` (trigger chặn UPDATE/DELETE): toàn bộ mã đủ điều kiện, hạng, điểm,
   mã băm cấu hình, vốn. Top-N được đánh dấu `is_pick`.
2. Vào lệnh: snapshot liên tục đầu tiên ≥ `t₀ + trễ` (mặc định 60 giây; nên ≥ độ trễ P95 đo được), ăn phía bán theo vốn Q.
   Ra lệnh: cùng giờ của phiên thứ h sau đó, ăn phía mua đúng số cổ phiếu đã mua. Lợi suất ròng
   `= bán × (1 − phí_bán − thuế) / (mua × (1 + phí_mua)) − 1`. Bán không hết do thiếu độ sâu → gắn `EXIT_PARTIAL`.
3. So sánh: (a) trung bình mọi mã đủ điều kiện cùng điều kiện thực thi; (b) phân phối trung bình của top-N **ngẫu nhiên**
   (2.000 lần, không hoàn lại) → hạng phần trăm của rổ đã chọn; (c) **IC hạng** (Spearman giữa điểm ròng và lợi suất giữa-sang-giữa
   của mọi mã đủ điều kiện); (d) khoảng tin cậy 95% bootstrap của mức vượt trội qua các lần chốt.
4. Chống nhìn trước: `compute_features` chỉ dùng `ts ≤ as_of` (test đầu độc dữ liệu tương lai); ngưỡng cố định từ phiên hiệu chỉnh;
   danh sách bất biến; picks chốt trước khi biết giá ra.

**Diễn giải trung thực.** Với 5-10 phiên và top-N = 5, số quan sát rất ít, khoảng tin cậy sẽ rộng. Kết quả chỉ là **bằng chứng sơ bộ và kiểm tra quy trình**;
không được tuyên bố bộ lọc "có lợi nhuận". Kiểm tra sự đúng đắn của khung: trên dữ liệu mô phỏng bước ngẫu nhiên (không có lợi thế), mức vượt trội ≈ 0 và IC ≈ 0
(đã chạy thử: vượt trội TB +0,03%, IC TB −0,20 với 3 lần chốt - nhiễu).

## 7. Chuẩn hóa thời gian và đơn vị
Mọi thời gian ở Asia/Ho_Chi_Minh (UTC+7). Giá VND; khối lượng cổ phiếu; giá trị VND. `price_scale`/`volume_scale`/`value_scale` trong
`neo_field_map.yaml` quy đổi từ đơn vị của API.

## 8. Giới hạn
- Chỉ 3 mức giá, không thấy lệnh ẩn/lệnh ngầm; sổ lệnh thay đổi trong lúc khớp không được mô hình hóa.
- Chi phí tính tại thời điểm snapshot, không phải thời điểm khớp thực; không có tác động của chính lệnh lên giá.
- Vốn vượt độ sâu: chỉ cờ (hoặc ước lượng căn bậc hai với tham số giả định).
- RVOL cần ≥ 3 phiên trước; ADV chỉ có số phiên đã thu thập (hoặc nguồn bổ trợ) - ghi rõ số phiên dùng.
- Trọng số, λ, ngưỡng quy ước là giả định tiên nghiệm; chưa được tối ưu hay kiểm định ngoài mẫu quy mô lớn.
- Giá tham chiếu/điều chỉnh quyền: bỏ các mã có sự kiện quyền trong cửa sổ forward-test (chưa tự động hóa).
- Độ trễ/đồng bộ đồng hồ giữa máy thu thập và sàn chưa đo (cần `probe_neo.py`).

## 9. Tài liệu học thuật tham khảo (để trích dẫn; kiểm tra lại thông tin xuất bản trước khi đưa vào báo cáo)
- Amihud, Y. (2002). Illiquidity and stock returns. *Journal of Financial Markets*.
- Perold, A. (1988). The implementation shortfall. *Journal of Portfolio Management*.
- Almgren, R., Chriss, N. (2000). Optimal execution of portfolio transactions. *Journal of Risk*.
- Cont, R., Kukanov, A., Stoikov, S. (2014). The price impact of order book events. *Journal of Financial Econometrics*.
- Parkinson, M. (1980). The extreme value method for estimating the variance of the rate of return. *Journal of Business*.
- Grinold, R., Kahn, R. *Active Portfolio Management* (IC, quy tắc cơ bản của luật chủ động).
