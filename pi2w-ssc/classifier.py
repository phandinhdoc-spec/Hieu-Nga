"""BỘ NÃO PHÂN LOẠI RÁC: câu hỏi gửi Gemini + cách "đọc hiểu" câu trả lời.

Làm sao để máy "nói" đúng và không nói linh tinh?
  1. Ta dặn Gemini (trong biến PROMPT bên dưới) CHỈ ĐƯỢC trả lời bằng vài MÃ cố định:
         VO_CO       = rác vô cơ        HUU_CO = rác hữu cơ     KHAC = rác khác
         KHONG_THAY  = không thấy vật   SAC_NHON = vật sắc nhọn (đi kèm một mã nhóm)
  2. Hàm parse_reply() đọc mã đó.
  3. Pi tự chọn câu thông báo có sẵn (bảng SPOKEN) rồi đọc to.
Nhờ vậy người dùng chỉ nghe đúng những câu đã định sẵn, dù Gemini có "lan man" cỡ nào.

Muốn chỉnh cách phân loại (ví dụ thêm quy tắc mới) thì sửa nội dung PROMPT.
Nhưng nhớ: PROMPT phải ngắn hơn MAX_PROMPT_CHARACTERS ký tự.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


class ReplyError(ValueError):
    """Gemini trả về nội dung không đọc được thành kết quả phân loại (ví dụ trả lời lung tung)."""


VO_CO = "VO_CO"
HUU_CO = "HUU_CO"
KHAC = "KHAC"
KHONG_THAY = "KHONG_THAY"
SAC_NHON = "SAC_NHON"
BAT = "BAT"  # thông báo bật/tắt chế độ liên tục (không phải mã Gemini)
TAT = "TAT"

# Bốn kết quả "nhóm" mà Gemini được phép trả về.
CATEGORIES = (VO_CO, HUU_CO, KHAC, KHONG_THAY)

# BẢNG CÂU THÔNG BÁO: mã -> câu Pi sẽ đọc.
# Muốn đổi lời đọc thì sửa chữ ở đây (cache cũ tự bị bỏ vì tên file cache tính từ nội dung câu).
# Các câu được nhờ server đọc một lần rồi lưu vào thư mục cache/ trên Pi.
SPOKEN = {
    VO_CO: "Rác vô cơ.",
    HUU_CO: "Rác hữu cơ.",
    KHAC: "Rác khác.",
    SAC_NHON: "Cảnh báo, đây là vật sắc nhọn.",
    KHONG_THAY: "Chưa thấy vật. Hãy đưa vật vào trước camera.",
    BAT: "Đã bật phân tích liên tục.",
    TAT: "Đã tắt phân tích.",
}

# Server giới hạn 2.000 ký tự cho trường text; giữ dư để an toàn.
MAX_PROMPT_CHARACTERS = 1800

# PROMPT = "bài giao việc" gửi cho Gemini cùng với mỗi tấm ảnh.
# Các quy tắc phân loại (vô cơ/hữu cơ/khác, túi bóng, vật sắc nhọn) đều nằm ở đây.
# Dấu \ ở cuối dòng nghĩa là "nối với dòng dưới, không xuống dòng".
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


@dataclass(frozen=True)
class Verdict:
    """PHÁN QUYẾT: kết quả cuối cùng sau khi đọc câu trả lời của Gemini."""

    # category: nhóm rác. Có thể None nếu Gemini chỉ báo "sắc nhọn" mà không nói nhóm.
    # sharp: có phải vật sắc nhọn không (cần cảnh báo).
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
    """Đọc câu trả lời của Gemini thành Verdict; ném ReplyError nếu không rõ.

    Gemini được dặn trả mã như "SAC_NHON VO_CO", nhưng đôi khi nó vẫn viết "Rác vô cơ"
    hay bọc trong dấu ``. Hàm này "dễ tính": hiểu cả các cách viết đó, nhưng KHÔNG đoán mò:
    trả về nhiều nhóm cùng lúc, hoặc không có mã nào, thì báo lỗi để Pi kêu báo lỗi.
    """
    folded = _fold(text)
    sharp = _has_token(folded, SAC_NHON)
    # Tìm xem trong câu trả lời có những nhóm nào.
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
    """Chuẩn hóa chữ để dễ so sánh: IN HOA, bỏ dấu tiếng Việt, ký tự lạ thành dấu '_'.

    Ví dụ: "rác vô cơ." -> "_RAC_VO_CO_" ; "`HUU_CO`" -> "_HUU_CO_".
    Hai dấu '_' ở đầu và cuối giúp tìm từ nguyên vẹn (xem _has_token).
    """
    text = text.replace("đ", "d").replace("Đ", "D")
    stripped = "".join(
        character
        for character in unicodedata.normalize("NFD", text.upper())
        if unicodedata.category(character) != "Mn"
    )
    return "_" + re.sub(r"[^A-Z0-9]+", "_", stripped).strip("_") + "_"


def _has_token(folded: str, token: str) -> bool:
    """Câu có chứa NGUYÊN CẢ TỪ `token` không? (để "KHACH" không bị nhầm thành "KHAC")."""
    return f"_{token}_" in folded
