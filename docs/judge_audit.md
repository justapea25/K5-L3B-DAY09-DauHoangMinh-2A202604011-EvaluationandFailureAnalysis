# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend REPLAY, verdict judge lưu sẵn trong CSV; FAIL = lớp dương).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** — confusion tp=24 fp=4 fn=6 tn=66 | **dùng** (chỉ cho tone, không cho tiền) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** (κ, R) — confusion tp=9 fp=0 fn=21 tn=70 | **loại** |

Tỉ lệ fail hiệu chỉnh Rogan-Gladen: tone quan sát 0.28 → hiệu chỉnh 0.30; helpful quan sát 0.09 → hiệu chỉnh 0.30. Judge helpful báo tỉ lệ lỗi chỉ bằng 1/3 thực tế.

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | tone H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | **Người** | Xưng "em" + "nha" quá suồng sã. Rubric thêm: *xưng hô phải là "LogiX" – "anh/chị"; xưng "em/bạn", tiểu từ "nha/nhé" ⇒ FAIL*. |
| 2 | tone H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ…" | PASS | FAIL | **Người** | Cùng lỗi xưng hô ("bạn"). Gộp vào luật xưng hô ở #1, kèm 2 ví dụ few-shot FAIL. |
| 3 | tone H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | **Người** | Judge bị đánh lừa bởi "Dạ, vui lòng". Rubric thêm: *câu mệnh lệnh / cấm khách liên hệ ⇒ FAIL bất kể kính ngữ mở đầu*. |
| 4 | tone H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì "thiếu xin lỗi". Rubric ghi rõ: *xin lỗi KHÔNG bắt buộc; ngắn gọn, đủ ý, lịch sự ⇒ PASS*. |
| 5 | tone H-051 "…LogiX đã refund 90.000đ…" | FAIL | PASS | **Người** | Style guide CS cho phép "refund". Thêm danh sách thuật ngữ tiếng Anh được phép vào rubric. |
| 6 | tone H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Nhãn người sai (đọc nhầm ticket). Hành động: **sửa nhãn người**, không sửa rubric; ghi vào changelog nhãn. |
| 7 | tone H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | **Người** | Rubric thêm: *emoji trong ngữ cảnh khiếu nại ⇒ FAIL*. |
| 8 | tone H-094 "Da, LogiX da hoan 40.000đ…" (mất dấu) | PASS | FAIL | **Người** | Rubric thêm: *tiếng Việt không dấu / dịch máy ⇒ FAIL*. |
| 9 | helpful HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | **Người** | Judge không thấy ledger nên không thể biết số tiền sai. **Không sửa được bằng rubric** → chuyển sang code: `reply_matches_ledger` (FM-08). |
| 10 | helpful HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | **Người** | Không nêu kết quả/số tiền, không có bước tiếp theo. Rubric helpful thêm: *phải nêu trạng thái + số tiền (nếu có) + bước tiếp theo*. |

## Kết luận
- **tone_ok: dùng được** như metric theo dõi phong cách (κ=0.757, P=0.857, R=0.80 đều trên sàn). Sau khi sửa rubric (#1–#5, #7, #8) và nhãn (#6) cần calibrate lại trên tập nhãn mới.
- **helpful: loại, không được dùng làm gate.** R=0.30: judge bỏ sót 21/30 reply mà người chấm FAIL; κ=0.375 < 0.6. P=1.0 chỉ có nghĩa là judge hiếm khi nói FAIL. Lỗi sót tập trung vào reply nói số tiền khác ledger (18/21 case có note "ledger ghi …") và reply mơ hồ "Ok bạn… xử lý rồi nhé". Judge chỉ đọc reply, không đọc ledger, nên về bản chất không chấm được tính đúng của tiền. Dùng nó làm gate sẽ cho qua đúng lỗi FM-08 mà ta cần chặn. Theo quy tắc của lab, tiền luôn chấm bằng code: `reply_matches_ledger` (blocking, min 1.0).
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng/tiêu chí); cần nhãn người mới để có held-out thật, và cần đo lại sau khi đổi rubric (prompt mới = judge mới).
