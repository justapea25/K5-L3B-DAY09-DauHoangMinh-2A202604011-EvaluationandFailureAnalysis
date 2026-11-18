# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

## Case: `seeded_regression` C-014@11 — trừ tiền hai lần (FM-05)

```
== seeded_regression C-014@11  lab8 grader: FAIL (proposal_mismatch)
   1 handoff        {... "task": "check_applicable_policy" ...}
   2 investigator   {"lookup_order": {"visible": true, "order": {"order_id": "O-515", ...}}}
   3 quote          {"amount_vnd": 150000, "clause_ids": ["SHIP-LATE-03", "DMG-04"], ...}
   4 refund_history {"refund_count": 1, "refunded_vnd": 30000}
   5 proposal       {"amount_vnd": 120000}
   6 reply          {"text": "Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."}
-- ledger vs label
  refund_vnd     ledger=90000    label=120000   <-- differs
  status         result=resolved label=resolved
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, report `E-seeded_regression-20261118-529e` (`reports/eval_seeded_regression.json`, row E-014 seed 11) |
| Triệu chứng | `pass_rate` FAIL (`proposal_mismatch`), `refund_amount_correct` FAIL (ledger 90.000 ≠ nhãn 120.000), `proposal_correct` FAIL (120.000 ≠ quote 150.000), `reply_matches_ledger` FAIL (reply nói 120.000đ, ledger 90.000đ). Status vẫn `resolved` nên nhìn reply thì tưởng đúng. |
| Bước sai đầu tiên | **Event 5** `proposal {"amount_vnd": 120000}`: agent tự lấy quote 150.000 trừ 30.000 đã hoàn trước đó. |
| Vì sao là bước *đầu tiên* | Event 1–2 (handoff, đọc đơn O-515 từ DB) đúng; event 3 quote của `compute_compensation` = 150.000 đúng (max-of-eligible, khớp `proposal_amount` của nhãn); event 4 đọc lịch sử 30.000 là dữ kiện đúng. Sai bắt đầu khi agent **dùng** con số đó để tự tính tiền, trái `model.may_compute_money: false`: host (`cap_per_order`) vốn đã trừ phần đã hoàn, nên ledger bị trừ lần hai → 90.000. Reply (event 6) sai theo, là hệ quả chứ không phải nguyên nhân. |
| Failure mode | **FM-05** pre_deducted (kéo theo triệu chứng FM-08 ở reply) |
| Đối chứng | `fixed C-014@11`: event 3 quote 150.000 → **không có** event `refund_history` / `proposal` → host ghi 120.000 = nhãn; reply "120.000đ" khớp ledger; lab8 PASS. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_lab9_trace_case_double_deduct_is_caught` (assert event `proposal` ngay sau `refund_history`, ledger 90.000, `proposal_correct`/`refund_amount_correct`/`reply_matches_ledger` = False) và `test_lab9_trace_case_fixed_control_passes` (cùng claim@seed trên `fixed` pass hết). Đã chạy: fail-detect trên variant lỗi, pass trên `fixed`. Chạy trong CI qua `-m student -k "lab9 and not advanced"`. Ở mức eval: metric `proposal_correct` (blocking) bắt lỗi này trên 15/70 dòng của `seeded_regression`. |
| Chưa chắc chắn | Trace không cho biết *vì sao* model trừ (prompt hay logic); MockLLM tất định nên không đo được tần suất trên model thật. Với C-013 cùng cơ chế lại ra `denied` (đề xuất 0) — ledger đúng 0 nên chỉ `proposal_correct` và lab8 bắt được, `refund_amount_correct` không. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
