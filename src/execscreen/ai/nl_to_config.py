"""Lớp AI TÙY CHỌN: dịch yêu cầu bằng ngôn ngữ tự nhiên thành bộ tham số có cấu trúc.

Nguyên tắc an toàn (cũng là nội dung phải nêu trong báo cáo):
  * AI chỉ ĐƯỢC PHÉP sinh tham số cấu hình (vốn, top-N, trọng số yếu tố...). Không nhìn thấy dữ liệu
    thị trường, không đưa ra nhận định hay khuyến nghị mua/bán.
  * Đầu ra bị kiểm tra bằng schema (Pydantic, cấm trường lạ, giới hạn khoảng giá trị);
    giao diện hiển thị tham số đã dịch để NGƯỜI DÙNG XÁC NHẬN trước khi chạy.
  * Luôn có bộ phân tích dựa trên quy tắc (rule_based_parse) làm phương án dự phòng, chạy offline.
  * `llm_callable` do bên ngoài cung cấp (nhận prompt, trả chuỗi JSON): có thể gắn bất kỳ mô hình nào;
    mặc định KHÔNG gắn mô hình nào và tính năng tắt (AI_ENABLED=false).
"""
from __future__ import annotations

import copy
import json
import re
from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

ALLOWED_FACTORS = ["mom_ref", "range_pos", "rvol_tod", "obi3", "range_pct", "foreign_net"]

SYSTEM_PROMPT = """Bạn chỉ làm một việc: chuyển yêu cầu của người dùng thành JSON tham số cho bộ lọc cổ phiếu.
Chỉ được dùng các khóa: capital_vnd (số, VND), top_n (số nguyên 1-30),
weights (đối tượng: tên yếu tố -> số từ 0 đến 5; tên hợp lệ: {factors}),
max_participation (0-1), cost_penalty_lambda (0-3).
Chỉ in JSON, không giải thích. Không đưa ra khuyến nghị đầu tư. Nếu yêu cầu không liên quan, in {{}}."""


class Overrides(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capital_vnd: Optional[float] = Field(default=None, gt=0, le=1e11)
    top_n: Optional[int] = Field(default=None, ge=1, le=30)
    weights: dict[str, float] = Field(default_factory=dict)
    max_participation: Optional[float] = Field(default=None, gt=0, le=1)
    cost_penalty_lambda: Optional[float] = Field(default=None, ge=0, le=3)

    @field_validator("weights")
    @classmethod
    def _weights_ok(cls, v):
        for k, w in v.items():
            if k not in ALLOWED_FACTORS:
                raise ValueError(f"yếu tố không hợp lệ: {k}")
            if not (0 <= w <= 5):
                raise ValueError(f"trọng số ngoài khoảng 0-5: {k}={w}")
        return v


def validate_overrides(text: str) -> Overrides:
    """Kiểm tra chuỗi JSON từ AI/người dùng. Ném ValueError nếu không hợp lệ."""
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("JSON phải là một đối tượng")
        return Overrides(**data)
    except (json.JSONDecodeError, ValidationError) as e:
        raise ValueError(f"Tham số không hợp lệ: {e}") from e


_UNITS = {"tỷ": 1e9, "ty": 1e9, "tr": 1e6, "triệu": 1e6, "trieu": 1e6, "k": 1e3, "nghìn": 1e3}


def rule_based_parse(text: str) -> Overrides:
    """Phân tích đơn giản bằng quy tắc, không cần mạng: 'vốn 300 triệu, top 8, ưu tiên thanh khoản'."""
    t = text.lower()
    data: dict = {}
    m = re.search(r"(?:vốn|von)\s*([\d.,]+)\s*(tỷ|ty|triệu|trieu|tr|nghìn|k)?", t)
    if m:
        num = float(m.group(1).replace(",", "."))
        data["capital_vnd"] = num * _UNITS.get(m.group(2) or "", 1.0)
    m = re.search(r"top\s*(\d+)", t)
    if m:
        data["top_n"] = int(m.group(1))
    w: dict[str, float] = {}
    if re.search(r"khối lượng|rvol|thanh khoản giao dịch", t):
        w["rvol_tod"] = 2.0
    if re.search(r"động lượng|momentum|tăng giá", t):
        w["mom_ref"] = 2.0
    if re.search(r"sổ lệnh|mất cân bằng|obi", t):
        w["obi3"] = 2.0
    if re.search(r"nước ngoài", t):
        w["foreign_net"] = 2.0
    if w:
        data["weights"] = w
    if re.search(r"ít chi phí|chi phí thấp|rẻ", t):
        data["cost_penalty_lambda"] = 1.0
    return Overrides(**data)


def llm_parse(text: str, llm_callable: Callable[[str], str]) -> Overrides:
    """Gọi mô hình ngôn ngữ (do người dùng gắn vào), rồi KIỂM TRA nghiêm ngặt đầu ra."""
    prompt = SYSTEM_PROMPT.format(factors=", ".join(ALLOWED_FACTORS)) + "\n\nYêu cầu: " + text
    raw = llm_callable(prompt).strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    return validate_overrides(raw)


def apply_overrides(cfg: dict, ov: Overrides) -> tuple[dict, Optional[float]]:
    """Trả về (cấu hình mới, vốn mới nếu có). Không sửa cấu hình gốc."""
    c = copy.deepcopy(cfg)
    for k, w in ov.weights.items():
        if k in c["factors"]:
            c["factors"][k]["weight"] = w
            c["factors"][k]["enabled"] = w > 0
    if ov.top_n is not None:
        c["forward_test"]["top_n"] = ov.top_n
    if ov.max_participation is not None:
        c["gates"]["max_participation"] = ov.max_participation
    if ov.cost_penalty_lambda is not None:
        c["scoring"]["cost_penalty_lambda"] = ov.cost_penalty_lambda
    return c, ov.capital_vnd
