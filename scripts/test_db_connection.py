#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MySQL 数据库连通性测试脚本
使用 .env 文件中的配置测试数据库连接
"""

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    import pymysql
except ImportError as e:
    print(f"❌ 缺少必要的依赖包: {e}")
    print("\n请安装依赖:")
    print("  pip install python-dotenv pymysql")
    sys.exit(1)


def load_db_config():
    """从 .env 文件加载数据库配置"""
    # 加载 .env 文件
    env_path = Path(__file__).parent / '.env'
    if not env_path.exists():
        print(f"❌ 未找到 .env 文件: {env_path}")
        sys.exit(1)

    load_dotenv(env_path)

    config = {
        'host': os.getenv('DB_HOST'),
        'port': int(os.getenv('DB_PORT', 3306)),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'database': os.getenv('DB_NAME'),
    }

    # 检查必需的配置项
    missing = [k for k, v in config.items() if not v]
    if missing:
        print(f"❌ .env 文件中缺少配置: {', '.join(missing)}")
        sys.exit(1)

    return config


def test_connection(config):
    """测试数据库连接"""
    print("=" * 60)
    print("MySQL 数据库连通性测试")
    print("=" * 60)
    print(f"\n📋 连接配置:")
    print(f"  主机: {config['host']}")
    print(f"  端口: {config['port']}")
    print(f"  用户: {config['user']}")
    print(f"  数据库: {config['database']}")
    print(f"  密码: {'*' * len(config['password'])}")

    print(f"\n🔄 正在连接...")

    connection = None
    try:
        # 建立连接
        connection = pymysql.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config['database'],
            connect_timeout=10,
            charset='utf8mb4'
        )

        print("✅ 连接成功!")

        # 获取数据库版本信息
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            print(f"\n📊 数据库信息:")
            print(f"  MySQL 版本: {version}")

            # 获取当前数据库
            cursor.execute("SELECT DATABASE()")
            current_db = cursor.fetchone()[0]
            print(f"  当前数据库: {current_db}")

            # 获取数据库中的表数量
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            print(f"  表数量: {len(tables)}")

            if tables:
                print(f"\n📋 数据库表列表:")
                for idx, table in enumerate(tables, 1):
                    print(f"  {idx}. {table[0]}")

        print("\n" + "=" * 60)
        print("✅ 数据库连通性测试通过")
        print("=" * 60)
        return True

    except pymysql.Error as e:
        print(f"\n❌ 连接失败!")
        print(f"  错误代码: {e.args[0]}")
        print(f"  错误信息: {e.args[1]}")
        print("\n" + "=" * 60)
        print("❌ 数据库连通性测试失败")
        print("=" * 60)
        return False

    except Exception as e:
        print(f"\n❌ 发生未预期的错误: {type(e).__name__}: {e}")
        print("\n" + "=" * 60)
        print("❌ 数据库连通性测试失败")
        print("=" * 60)
        return False

    finally:
        if connection:
            connection.close()
            print("\n🔌 连接已关闭")


def main():
    """主函数"""
    try:
        config = load_db_config()
        success = test_connection(config)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ 程序执行失败: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
