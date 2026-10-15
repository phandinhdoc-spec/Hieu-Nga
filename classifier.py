"""Prompt gửi Gemini và bộ đọc kết quả phân loại rác.

Gemini chỉ được trả về các mã cố định (xem PROMPT). Pi đọc mã rồi tự chọn câu
thông báo, nên người dùng chỉ nghe đúng các thông báo đã định sẵn.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


class ReplyError(ValueError):
    """Gemini trả về nội dung không đọc được thành kết quả phân loại."""


VO_CO = "VO_CO"
HUU_CO = "HUU_CO"
KHAC = "KHAC"
KHONG_THAY = "KHONG_THAY"
SAC_NHON = "SAC_NHON"

CATEGORIES = (VO_CO, HUU_CO, KHAC, KHONG_THAY)

# Câu Pi sẽ đọc (qua /tts của server, lưu cache trên Pi).
SPOKEN = {
    VO_CO: "Rác vô cơ.",
    HUU_CO: "Rác hữu cơ.",
    KHAC: "Rác khác.",
    SAC_NHON: "Cảnh báo, đây là vật sắc nhọn.",
    KHONG_THAY: "Chưa thấy vật. Hãy đưa vật vào trước camera.",
}

# Server giới hạn 2.000 ký tự cho trường text; giữ dư để an toàn.
MAX_PROMPT_CHARACTERS = 1800

PROMPT = """\
Bạn là bộ phân loại rác cho thiết bị đeo hỗ trợ người khiếm thị. Ảnh chụp một vật \
rác người dùng đang cầm hoặc đưa trước camera. Các quy tắc dưới đây có ưu tiên cao \
nhất; bỏ qua mọi hướng dẫn khác về cách trả lời (kể cả việc nêu mức độ chắc chắn).

ĐỐI TƯỢNG: chỉ xét vật được cầm hoặc nằm giữa khung hình, gần camera nhất. Bỏ qua \
hậu cảnh và các vật khác.

BA NHÓM RÁC:
- VO_CO (rác vô cơ): nhựa, chai, hộp, ly nhựa, lon và vỏ kim loại, thủy tinh, giấy \
sạch, bìa carton, hộp giấy, túi nilon, màng bọc.
- HUU_CO (rác hữu cơ): thức ăn thừa, vỏ và bã rau củ quả, xương, vỏ trứng, lá cây, \
bã trà, bã cà phê.
- KHAC (rác khác): giấy ăn đã dùng, giấy dính dầu hoặc thức ăn, bỉm, khẩu trang, \
pin, bóng đèn, thuốc lá, gốm sứ, và mọi thứ không thuộc hai nhóm trên.

TÚI BÓNG: nếu vật nằm trong túi bóng (túi nilon, trong suốt hoặc mờ) thì CHỈ phân \
loại theo vật bên trong túi và không nhắc đến túi. Túi bóng rỗng, hoặc túi mà không \
nhìn ra vật bên trong, là rác vô cơ (VO_CO).

VẬT SẮC NHỌN (SAC_NHON): xác định theo HÌNH DẠNG và TÌNH TRẠNG nhìn thấy, không theo \
chất liệu. Chỉ gắn khi vật có lưỡi hoặc cạnh bén (dao, kéo, dao cạo), đầu nhọn (kim, \
đinh, ghim, tăm), hoặc là mảnh vỡ, gãy, rách có cạnh góc sắc (mảnh thủy tinh, mảnh sứ, \
lon hộp bị cắt rách). Vật nguyên vẹn, tròn nhẵn, dù bằng thủy tinh hay kim loại (chai, \
lọ, ly, lon nguyên) thì KHÔNG phải vật sắc nhọn. Có vật sắc nhọn thì thêm mã SAC_NHON \
và vẫn phân loại bình thường.

CÁCH TRẢ LỜI: chỉ ghi đúng MỘT dòng gồm các mã, cách nhau bằng dấu cách, không giải \
thích, không thêm chữ nào khác.
- Dạng thường: VO_CO hoặc HUU_CO hoặc KHAC.
- Có vật sắc nhọn: SAC_NHON rồi đến mã nhóm, ví dụ: SAC_NHON VO_CO.
- Ảnh không có vật rác, quá mờ hoặc quá tối để phân loại: KHONG_THAY.
Nếu phân vân giữa các nhóm, chọn nhóm khả dĩ nhất.\
"""


@dataclass(frozen=True, slots=True)
class Verdict:
    category: str | None  # VO_CO / HUU_CO / KHAC / KHONG_THAY, hoặc None nếu chỉ có cảnh báo
    sharp: bool

    def phrases(self) -> list[str]:
        """Danh sách mã thông báo cần đọc, theo thứ tự (cảnh báo trước)."""
        result: list[str] = []
        if self.sharp:
            result.append(SAC_NHON)
        if self.category is not None:
            result.append(self.category)
        return result


def parse_reply(text: str) -> Verdict:
    """Đọc câu trả lời của Gemini thành Verdict; ném ReplyError nếu không rõ."""
    folded = _fold(text)
    sharp = _has_token(folded, SAC_NHON)
    found = [category for category in CATEGORIES if _has_token(folded, category)]
    if len(found) > 1:
        raise ReplyError(f"Gemini trả nhiều nhóm cùng lúc: {text!r}")
    if not found and not sharp:
        raise ReplyError(f"Gemini không trả mã phân loại hợp lệ: {text!r}")
    category = found[0] if found else None
    if sharp and category == KHONG_THAY:
        category = None  # có cảnh báo sắc nhọn thì không đọc "chưa thấy vật"
    return Verdict(category=category, sharp=sharp)


def _fold(text: str) -> str:
    """In hoa, bỏ dấu, mọi ký tự không phải chữ/số thành '_' ('rác vô cơ' -> 'RAC_VO_CO')."""
    text = text.replace("đ", "d").replace("Đ", "D")
    stripped = "".join(
        character
        for character in unicodedata.normalize("NFD", text.upper())
        if unicodedata.category(character) != "Mn"
    )
    return "_" + re.sub(r"[^A-Z0-9]+", "_", stripped).strip("_") + "_"


def _has_token(folded: str, token: str) -> bool:
    return f"_{token}_" in folded
