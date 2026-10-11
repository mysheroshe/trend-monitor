"""邮件发送器"""

import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import markdown
from dotenv import load_dotenv

DEFAULT_SMTP_SERVER = "smtp.gmail.com"
DEFAULT_SMTP_PORT = "587"


def _clean_env(name, default=""):
    """Read an environment variable, treating blank values as "not provided".

    GitHub Actions substitutes an *empty string* for secrets that are not
    configured, so ``os.getenv("SMTP_PORT", "587")`` returns ``""`` on CI and
    ``int("")`` used to crash the whole daily run.
    """
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def send_email_report(report_content, subject=None):
    """发送邮件报告

    邮件是可选功能：缺少配置或发送失败时只打印警告并返回 False，
    绝不会抛异常中断日报流水线。

    Args:
        report_content: 报告内容（Markdown格式）
        subject: 邮件主题（可选，默认为日报主题）

    Returns:
        bool: 发送成功返回 True；未配置或发送失败返回 False
    """
    try:
        return _send_email_report(report_content, subject)
    except Exception as exc:  # 邮件问题绝不能导致整个流程失败
        print(f"  ❌ 邮件发送失败（已跳过，不影响日报）: {type(exc).__name__}: {exc}")
        return False


def _send_email_report(report_content, subject=None):
    load_dotenv()

    # 读取配置（空字符串视为“未配置”）
    smtp_server = _clean_env("SMTP_SERVER", DEFAULT_SMTP_SERVER)
    smtp_port_raw = _clean_env("SMTP_PORT", DEFAULT_SMTP_PORT)
    sender_email = _clean_env("EMAIL_SENDER")
    sender_password = _clean_env("EMAIL_PASSWORD")
    recipient_email = _clean_env("EMAIL_RECEIVER")

    try:
        smtp_port = int(smtp_port_raw)
    except (TypeError, ValueError):
        print(f"  ⚠️  SMTP_PORT 配置无效（{smtp_port_raw!r}），跳过发送邮件")
        return False

    # 检查必要配置
    if not all([sender_email, sender_password, recipient_email]):
        print("  ⚠️  邮件配置不完整，跳过发送")
        print("     请检查 EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER"
              "（未配置时日报仍会正常生成并提交）")
        return False

    # 创建邮件主题
    today = datetime.now().strftime("%Y-%m-%d")
    if subject is None:
        subject = f"AI/Tech 趋势日报 - {today}"
    else:
        subject = f"{subject} - {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient_email

    # 纯文本版本
    text_content = report_content

    # HTML版本（使用markdown库转换）
    html_content = markdown_to_html(report_content)

    msg.attach(MIMEText(text_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # 发送邮件
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, msg.as_string())
        return True
    except smtplib.SMTPAuthenticationError:
        print("  ❌ 邮件认证失败，请检查邮箱和密码")
        print("     Gmail用户需要使用应用专用密码")
        return False
    except smtplib.SMTPException as e:
        print(f"  ❌ 邮件发送失败: {e}")
        return False
    except Exception as e:
        print(f"  ❌ 发送错误: {e}")
        return False


def markdown_to_html(md_content):
    """使用markdown库将Markdown转换为HTML"""
    body = markdown.markdown(md_content, extensions=['extra', 'nl2br'])
    return f'<html><body style="font-family: Arial; max-width: 800px; margin: 0 auto; padding: 20px;">{body}</body></html>'
