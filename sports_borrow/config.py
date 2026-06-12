import os


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(BASE_DIR, "sports_borrow.db")
SECRET_KEY = "sports-borrow-system-dev-key"

CATEGORIES = ["球类", "球拍类", "健身类", "其他"]

RECORD_STATUS = {
    "pending": "待审核",
    "approved": "已通过",
    "rejected": "已驳回",
    "returned": "已归还",
    "overdue": "已逾期",
}

EQUIPMENT_IMAGE_BY_NAME = {
    "篮球": "images/split/item-basketball.png",
    "足球": "images/split/item-soccer.png",
    "排球": "images/split/item-volleyball.png",
    "羽毛球拍": "images/split/item-badminton-racket.png",
    "羽毛球": "images/split/item-badminton.png",
    "乒乓球": "images/split/item-pingpong.png",
    "跳绳": "images/split/item-rope.png",
    "哑铃": "images/split/item-dumbbell.png",
    "瑜伽垫": "images/split/item-yoga-mat.png",
    "标志桶": "images/split/item-cone.png",
}

EQUIPMENT_IMAGE_BY_CATEGORY = {
    "球类": "images/split/item-basketball.png",
    "球拍类": "images/split/item-badminton.png",
    "健身类": "images/split/item-rope.png",
    "其他": "images/split/item-cone.png",
}
