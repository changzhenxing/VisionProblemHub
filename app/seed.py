from datetime import date, timedelta
from sqlalchemy import select
from .db import Base, engine, SessionLocal
from .models import User

Base.metadata.create_all(bind=engine)

def seed():
    with SessionLocal() as db:
        if not db.scalar(select(User).limit(1)):
            db.add(User(name="管理员",role="团队负责人")); db.commit()
            print("已创建默认用户：管理员")
        else:
            print("已有用户，跳过初始化")

if __name__=="__main__": seed()
