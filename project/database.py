from pymongo import MongoClient

from project.settings import MONGODB


def connect_db():
    db = MongoClient(**MONGODB['connection'])[MONGODB['dbname']]
    db.log.create_index([('date', 1), ('type', 1)])
    return db
