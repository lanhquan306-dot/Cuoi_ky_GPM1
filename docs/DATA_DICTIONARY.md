# Từ điển dữ liệu

Đơn vị chuẩn: giá = VND; khối lượng = cổ phiếu; giá trị = VND; thời gian = ISO 8601 +07:00 (Asia/Ho_Chi_Minh).
Cột "NEO" ghi trạng thái xác nhận: **Đề** = có trong danh sách trường đề nêu; **?** = cần xác nhận bằng `probe_neo.py`.

## Bảng `snapshots` (một dòng = trạng thái của một mã tại một thời điểm lấy mẫu)
| Cột | Kiểu | Ý nghĩa | NEO |
|---|---|---|---|
| symbol | text | Mã chứng khoán (viết hoa) | Đề |
| ts | text ISO | Thời gian của snapshot (giờ VN) | ? (tin có thời gian sàn hay không) |
| trade_date | text | Ngày giao dịch `YYYY-MM-DD` | suy ra |
| source | text | `neo` / `mock` (mock = mô phỏng) | hệ thống |
| phase | text | PRE / ATO / CONTINUOUS / BREAK / ATC / CLOSED (suy từ `ts` và `config.sessions`) | hệ thống |
| q_flags | text | Cờ chất lượng, phân tách bằng dấu phẩy: NO_QUOTE, NONCONT, LATE | hệ thống |
| ingest_ts | text ISO | Thời điểm máy thu thập nhận tin (đo độ trễ) | hệ thống |
| ref, ceiling, floor | real | Giá tham chiếu, trần, sàn | Đề |
| last, open, high, low | real | Giá khớp gần nhất, mở cửa, cao nhất, thấp nhất trong ngày | Đề |
| cum_volume, cum_value | real | Khối lượng / giá trị khớp **cộng dồn trong ngày** | Đề (xác nhận là cộng dồn) |
| bid{1,2,3}_p / _v | real | Giá / khối lượng chào mua mức 1-3 (1 = tốt nhất) | Đề |
| ask{1,2,3}_p / _v | real | Giá / khối lượng chào bán mức 1-3 | Đề |
| fbuy_vol, fsell_vol | real | Khối lượng nước ngoài mua / bán (cộng dồn) | Đề (kênh nào?) |
| fbuy_val, fsell_val | real | Giá trị nước ngoài mua / bán (cộng dồn) | Đề |
| room_cur, room_total | real | Room nước ngoài còn lại / tổng | Đề (SDK SSI có bản tin room) |

Khóa duy nhất `(symbol, ts, source)`. Giá trị thiếu lưu NULL (không thay bằng 0).

## Bảng `quality_log`
`trade_date, source, issue, n` - số lần xảy ra mỗi loại sự cố. Mã sự cố: NO_SYMBOL, BAD_TS, FUTURE_TS, DUPLICATE, OUT_OF_ORDER,
NEG_VALUE, CUM_DECREASE, OUT_OF_BAND, CROSSED_BOOK (loại bỏ); NO_QUOTE, LATE, NONCONT (giữ, gắn cờ); ACCEPTED (số tin chấp nhận).

## Bảng `status`
`k, v`: `connected`, `last_msg_ts`, `msgs`, `source`, `last_error` - nhịp tim của bộ thu thập, giao diện đọc để hiển thị trạng thái kết nối.

## Bảng `picks` (bất biến)
`run_id` (`YYYYMMDD-HHMMSS` của thời điểm quyết định), `as_of`, `symbol`, `rank`, `is_pick` (top-N), `net_score`, `comp_score`,
`cost_p90_bps`, `capital`, `config_hash` (SHA-256 rút gọn của cấu hình), `created_at`. Trigger chặn UPDATE/DELETE.

## Đầu ra của `compute_features` / `score_table` (mỗi mã một dòng)
| Cột | Ý nghĩa |
|---|---|
| mom_ref, range_pos, range_pct, rvol_tod, obi3, foreign_net | Yếu tố thô (xem METHODS §3); `foreign_src` = direct / room_proxy / none |
| rvol_n_sessions | Số phiên trước dùng để tính RVOL |
| adv_value, participation | GTGD TB ngày (≤ 20 phiên trước); Q / ADV |
| cost_p50_bps, cost_p90_bps | Phân vị chi phí vòng trong cửa sổ lookback |
| spread_med_bps, buy_slip_med_bps, sell_slip_med_bps | Trung vị spread và trượt giá từng chiều |
| coverage_med, beyond_share | Độ phủ sổ lệnh (x vốn) trung vị; tỷ lệ snapshot vượt độ sâu |
| n_snaps, quote_ok | Số snapshot hợp lệ; đủ `min_snapshots` chưa |
| stale, stale_s, limit_locked | Cờ dữ liệu cũ / khóa trần-sàn |
| gate_reasons | Lý do bị loại (NO_QUOTE, LIMIT_LOCKED, STALE, PARTICIPATION, ADV_LOW, COST_HIGH, BEYOND_DEPTH, FEW_FACTORS) |
| comp_score, contrib_* | Điểm yếu tố tổng hợp và đóng góp từng yếu tố |
| net_score, score_0_100, rank | Điểm ròng, điểm 0-100, hạng (chỉ mã đủ điều kiện) |

## Ánh xạ NEO → trường chuẩn
Điền ở `config/neo_field_map.yaml` (đường dẫn dạng `a.b.0.c`; `price_scale`, `volume_scale`, `value_scale` để quy đổi đơn vị;
`ts_format` = epoch_ms / epoch_s / iso / ymd_hms / hms). **Chưa điền** vì chưa xác minh được cấu trúc tin thật.
