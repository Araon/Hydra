import logging
from datetime import datetime
from sqlalchemy import DateTime
from flask import Flask, request, jsonify
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
from sqlalchemy_utils import database_exists, create_database

from config import SQLALCHEMY_DATABASE_URI

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI


db = SQLAlchemy(app)
migrate = Migrate(app, db)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class Tasks(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    command = db.Column(db.String(), nullable=False)
    scheduled_at = db.Column(db.DateTime, nullable=False)
    picked_at = db.Column(db.DateTime)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    failed_at = db.Column(db.DateTime)

    def __init__(self, command, scheduled_at, picked_at=None, started_at=None, completed_at=None, failed_at=None):
        self.command = command
        self.scheduled_at = scheduled_at
        self.picked_at = picked_at
        self.started_at = started_at
        self.completed_at = completed_at
        self.failed_at = failed_at


@app.route("/schedule", methods=['POST'])
def post_schedule():
    data = request.json

    command_data = data.get('command')
    scheduled_at = data.get('scheduled_at')

    if not command_data or not scheduled_at:
        logger.error('Invalid POST request: Command and scheduled_at are required.')
        return jsonify({
            'error': 'Command and scheduled_at are required'
        }), 400

    try:
        scheduled_at = datetime.fromisoformat(scheduled_at)
    except ValueError:
        logger.error('Invalid ISO date format in POST request.')
        return jsonify({
            'error': 'Invalid ISO date format'
        }), 400

    new_task = Tasks(command=command_data, scheduled_at=scheduled_at)
    db.session.add(new_task)
    db.session.commit()

    logger.info('Task scheduled successfully.')

    return jsonify({
        'message': 'Task scheduled successfully',
        'task_id': new_task.id
    }), 201


@app.route("/schedule/<string:task_id>", methods=['GET'])
def get_schedule(task_id):
    task = Tasks.query.get(task_id)

    if not task:
        logger.error(f'Task with ID {task_id} not found.')
        return jsonify({
            'error': 'Task not found'
        }), 404

    task_data = {
        'id': task.id,
        'command': task.command,
        'scheduled_at': task.scheduled_at if task.scheduled_at else None,
        'picked_at': task.picked_at if task.picked_at else None,
        'started_at': task.started_at if task.started_at else None,
        'completed_at': task.completed_at if task.completed_at else None,
        'failed_at': task.failed_at if task.failed_at else None
    }
    logger.info(f'Task with ID {task_id} retrieved successfully.')
    return jsonify(task_data), 200


if __name__ == "__main__":
    engine = create_engine(SQLALCHEMY_DATABASE_URI)
    if not database_exists(engine.url):
        create_database(engine.url)
    Tasks.metadata.create_all(engine)
    app.run(host="0.0.0.0", port=5000)
