import uvicorn

from app.api.main import app
from app.logging_config import LOG_FILE_NAME, resolve_log_dir

if __name__ == "__main__":
    # app.api.main configures logging while importing the application.  Keep
    # this entry point's prompt in sync without installing a second handler.
    log_path = resolve_log_dir() / LOG_FILE_NAME
    print(f"服务日志文件：{log_path}")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8765,
        reload=False,
        log_config=None,
    )
