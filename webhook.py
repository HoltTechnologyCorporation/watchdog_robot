from tgram.webhook import build_wsgi_app

from watchdog_robot import WatchdogRobot

robot = WatchdogRobot() 
robot.set_opts({'mode': 'production'})
app = build_wsgi_app(robot)


if __name__ == '__main__':
    from bottle import run
    run(app)
