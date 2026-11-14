# Assignment 4 交接文档

> 用途：明天开新窗口时，把这份文档给 Claude 看，它就能接上今天的进度。
> 写给：我自己（初学者视角），以及接手这个项目的 Claude。
> 最后更新：2026-11-13

---

## 一、项目是什么

把 **Sakila 电影租赁数据库（MySQL，源）** 的数据，通过 SQLAlchemy ORM 搬运到
**本地分析库（SQLite，目标）**，建成一个小型数据仓库（星型模型）。

```
MySQL (Sakila)  ──读取──▶  Python ETL  ──写入──▶  SQLite (analytics.db)
   源 / source                                        目标 / target
```

**核心要求**：
1. 为 Sakila 的 15 张源表定义 ORM 模型。
2. 为分析库的维度表/桥接表/事实表定义 ORM 模型。
3. 用**两个独立的 session**：一个连源（MySQL），一个连目标（SQLite）。

---

## 二、文件结构与各自职责

```
assignment4/
├── .env                 ⚠️ 真实密码（不该进 git，但现在已经进了，见第六节）
├── .env.example         ✅ 密码模板，给别人照着填
├── .gitignore           ✅ 告诉 git 哪些文件不要提交
├── pyproject.toml       ✅ 项目依赖清单
├── uv.lock              ✅ 依赖的精确版本锁
├── analytics.db         ❌ 生成产物，不该进 git（现在没被忽略，要修）
├── .venv -> ~/.venvs/assignment4   ❌ 软链接，不进 git
└── src/
    ├── config.py        连接配置：造两个 engine + 两个 Session 工厂
    ├── models_source.py Sakila 源表的 ORM 模型（15 张）
    ├── models_target.py 分析库的 ORM 模型（11 张）
    ├── sync.py          ETL 逻辑（目前只有 init 写完了）
    └── cli.py           命令行入口（遥控器）
```

### 各文件在干什么（一句话版）

| 文件 | 职责 |
|---|---|
| `config.py` | 读 `.env` → 拼出两条数据库连接字符串 → 造 `source_engine`/`target_engine` → 造 `SourceSession`/`TargetSession` 两个工厂 |
| `models_source.py` | 把 Sakila 的 15 张表翻译成 Python 类，继承 `SourceBase` |
| `models_target.py` | 把分析库的 11 张表翻译成 Python 类，继承 `TargetBase` |
| `sync.py` | 真正搬数据的逻辑。目前只实现了 `init()` |
| `cli.py` | 把终端命令翻译成函数调用，自己不碰数据库 |

---

## 三、当前进度

### ✅ 已完成

- `config.py` — 两套 engine / session 全部就绪
- `models_source.py` — 15 张源表模型
- `models_target.py` — 11 张目标表模型（6 维度 + 2 桥接 + 2 事实 + 1 同步状态）
- `sync.py` 的 `init()` — 建表 + 填 `dim_date` + 填 `sync_state`
- `cli.py` — 4 个子命令注册好了，但只有 `init` 接上了实现

### ✅ 已验证跑通

```bash
uv run python -m src.cli init
# 2026-11-13 02:25:14 [INFO] init completed: tables created, dim_date and sync_state ready.
# 耗时 0.9 秒
```

验证结果（全部符合预期）：

| 检查项 | 结果 |
|---|---|
| 建出的表 | 11 张 ✅ |
| `dim_date` 行数 | 730（2005-01-01 ~ 2006-12-31 每天一行）✅ |
| `sync_state` 行数 | 15（每张源表一行书签）✅ |
| `sync_state` 初始水位 | 1970-01-01 ✅ |
| `dim_film` / `fact_rental` | 0 行（等 full-load）✅ |
| MySQL 连接 | 通 ✅ |

### ❌ 待完成

| 命令 | 状态 | 要做什么 |
|---|---|---|
| `full-load` | 未实现 | 把源库全部数据搬进分析库 |
| `incremental` | 未实现 | 只搬 `last_update > 水位` 的增量 |
| `validate` | 未实现 | 对比源库和目标库聚合结果是否一致 |

**下一步建议**：先写 `full_load()`，从最简单的 `DimActor`（无 join）开始，再做
需要 join 的 `DimFilm`（并 language）、`DimStore`/`DimCustomer`（并 city/country），
最后做需要「自然键→代理键」转换的事实表。

---

## 四、今天踩的坑（重点！）

### 坑 1：虚拟环境为什么会出问题

#### 症状
终端跑 `uv run python -m src.cli init`，**永远卡住不出结果**。按 Ctrl+C
后看到 traceback，最后一行是 `KeyboardInterrupt`。

#### 真相
**程序没崩，是卡住了 —— `KeyboardInterrupt` 是自己按 Ctrl+C 造成的。**

#### 排查过程（这个方法以后可以复用）

一层层缩小范围，每层都计时：

| 测试 | 耗时 | 结论 |
|---|---|---|
| 裸 Python 启动 | 0.03 秒 | Python 本身没问题 |
| `import json`（标准库） | 0.03 秒 | 标准库没问题 |
| `import dotenv`（第三方，纯 Python） | **16 秒** | 第三方包有问题 |
| `import pymysql` | 卡 >45 秒 | 确认 |
| `import sqlalchemy` | 卡几分钟 | 确认 |

**关键线索**：卡住时 `user` CPU 时间几乎是 **0** —— 进程在「干等」，不是在「算」。
这是等待系统 I/O 的典型特征。

**决定性实验**：在 `~/Documents` **外面**建一个临时虚拟环境，装同一个
sqlalchemy 2.1.8：

```
~/Documents 里面：卡几分钟
~/Documents 外面：1.7 秒
```

#### 根因
项目放在 `~/Documents` 下，这个目录被 **iCloud「桌面与文稿」同步**接管。
虚拟环境里有**上千个包文件**，每个文件第一次被读取时，都要先过一道
iCloud 同步检查（`fileproviderd`）。单个文件慢几秒，上千个累积 → 卡几分钟。

更糟的是：每次按 Ctrl+C 掐断 → 系统缓存没建立 → **下次又从头卡**，形成死循环。

#### 解决方案
**虚拟环境搬出 Documents，项目代码原地不动。**

```bash
# 1) 删掉卡顿的旧环境（虚拟环境可随时重建，删除安全）
rm -rf .venv

# 2) 把环境建到 Documents 外面
UV_PROJECT_ENVIRONMENT=/Users/wangying/.venvs/assignment4 uv sync

# 3) 用软链接让 .venv 透明指过去（这样日常命令写法完全不变）
ln -s /Users/wangying/.venvs/assignment4 .venv
```

做完之后：`import sqlalchemy` 从「几分钟」变成 **2 秒**。

> ⚠️ **注意顺序**：必须先建环境、后建软链接。如果 `.venv` 已经是软链接，
> `uv sync` 会报 `File exists (os error 17)`，因为 uv 想自己创建这个目录。
>
> 以后再遇到这个报错：`rm .venv` → 用 `UV_PROJECT_ENVIRONMENT=... uv sync` → 重新 `ln -s`。

#### 根治选项（还没做）
关掉 macOS 系统设置里的 **iCloud「桌面与文稿」同步**，整个 Documents 目录都会恢复正常速度。

---

### 坑 2：一个真正的代码 bug

环境修好后，立刻暴露出真正的错误：

```
ImportError: cannot import name 'DeclarativeBase' from 'sqlalchemy'
```

**原因**：`models_target.py` 第 6 行导入位置写错了。

```python
# ❌ 错误：这三个东西不在顶层 sqlalchemy
from sqlalchemy import DeclarativeBase, Mapped, mapped_column

# ✅ 正确：它们住在 sqlalchemy.orm 子模块
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
```

**记忆规则**：
- `sqlalchemy`（顶层）：建表相关的东西 —— `Date`、`ForeignKey`、`Numeric`、`create_engine`、`select`、`func`
- `sqlalchemy.orm`（ORM 子模块）：对象映射相关的东西 —— `DeclarativeBase`、`Mapped`、`mapped_column`、`relationship`、`sessionmaker`

`models_source.py` 本来就写对了，只有 target 这边漏了 `.orm`。

---

### 为什么今天的错误这么「严重」

其实它一点都不严重 —— **只是看起来吓人**。真实情况是两个小问题叠在一起：

1. **环境卡顿把真正的错误藏起来了**
   代码里的 `ImportError` 其实在第 6 行就会报，但因为导入 sqlalchemy 本身
   就卡死，程序根本走不到报错那一步。你看到的只有「卡住 + Ctrl+C」，
   完全没有有用信息。

2. **Ctrl+C 让问题自我延续**
   每次掐断，系统的扫描缓存就建不起来，下次重跑又从零开始卡。
   于是形成「怎么试都一样」的假象。

**教训**：
- 看到 `KeyboardInterrupt`，第一反应应该是「这是我自己按的，程序是卡住不是崩了」。
- 排查卡顿要**分层计时**：裸 Python → 标准库 → 单个第三方包 → 完整程序。
- `real` 时间长但 `user` CPU 时间接近 0 = **在等外部资源**，不是代码死循环。
- 遇到卡顿**不要立刻 Ctrl+C**，先让它跑完一次，很多「首次慢」的问题跑完一次就好了。

---

## 五、虚拟环境到底是什么（概念补课）

### 为什么需要虚拟环境

不同项目需要不同版本的库。A 项目要 sqlalchemy 1.4，B 项目要 2.1。
如果全装在系统 Python 里就会打架。

**虚拟环境 = 给每个项目一个独立的、隔离的 Python 包目录。**

```
系统 Python                    项目的 .venv
└── 不装项目依赖      vs       └── sqlalchemy 2.1.8
                                  pymysql 1.2.4
                                  python-dotenv 1.2.4
```

### `.venv` 里面是什么

```
.venv/
├── bin/python          ← 这个项目专用的 Python 解释器（软链接）
├── bin/pip
├── lib/python3.13/site-packages/   ← 所有第三方包装在这里（几千个文件）
└── pyvenv.cfg          ← 配置文件，标记这是个虚拟环境
```

**关键认知**：`.venv` 是**可以随时删掉重建的**。它不是你的劳动成果，
而是根据 `pyproject.toml` + `uv.lock` **生成出来的产物**。
删了用一条 `uv sync` 就能完整还原。

所以 —— **`.venv` 绝对不要提交到 GitHub**。

### uv 是什么

`uv` 是一个现代的 Python 包管理工具（比 pip 快很多）。常用命令：

```bash
uv sync                      # 按 pyproject.toml 安装所有依赖到 .venv
uv add sqlalchemy            # 新增一个依赖（会自动改 pyproject.toml）
uv remove sqlalchemy         # 删除一个依赖
uv run python xxx.py         # 用 .venv 里的 Python 跑脚本（不用手动 activate）
```

> 用 `uv run` 就不需要 `source .venv/bin/activate` 了，它会自动用对的环境。
> 今天开头那个 `VIRTUAL_ENV ... does not match` 的警告，就是因为手动 activate 了
> 另一个环境（conda 的 assignment4），和 uv 想用的 `.venv` 冲突了。**不要手动 activate，直接用 `uv run`。**

---

## 六、GitHub 该传什么、不该传什么（重点！）

### 判断标准（一句话）

> **「别人 clone 下来之后，能不能靠这些文件重建出完整的项目？」**
> 能重建出来的东西 → **不传**（生成产物）
> 重建所必需的东西 → **传**（源头）

### ✅ 应该传

| 文件 | 为什么 |
|---|---|
| `src/**.py` | 你的源代码，核心劳动成果 |
| `pyproject.toml` | 依赖清单，别人靠它知道要装什么 |
| `uv.lock` | 精确版本锁，保证别人装出和你一模一样的环境 |
| `.gitignore` | 告诉 git 忽略什么 |
| `.env.example` | 配置模板（**只有 key，没有真密码**） |
| `README.md` | 说明怎么跑起来 |
| `tests/**.py` | 测试代码 |

### ❌ 不该传

| 文件 | 为什么 |
|---|---|
| `.venv/` | 几千个文件、几百 MB，而且 `uv sync` 一条命令就能重建 |
| `__pycache__/`、`*.pyc` | Python 自动生成的字节码缓存 |
| `.env` | **包含真实密码！传上去就是泄密** |
| `analytics.db` | 程序生成的数据库文件，跑一次 ETL 就有了 |
| `.DS_Store` | macOS 的文件夹显示配置，纯垃圾 |

### `.env` 和 `.env.example` 的配合（标准做法）

这是业界通用模式，务必掌握：

```
.env            ← 真密码，只存在你本地，写进 .gitignore，永不提交
.env.example    ← 模板，只有 key 和占位符，提交到 GitHub
```

`.env.example`（**提交**）：
```
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password_here     ← 占位符，不是真密码
MYSQL_DB=sakila
SQLITE_PATH=analytics.db
```

`.env`（**不提交**）：
```
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=我的真实密码123          ← 真的
MYSQL_DB=sakila
SQLITE_PATH=analytics.db
```

**别人 clone 之后的流程**：
```bash
cp .env.example .env    # 复制模板
vim .env                # 填自己的密码
uv sync                 # 装依赖
uv run python -m src.cli init
```

### ⚠️⚠️ 当前项目有两个问题要修

#### 问题 1：`.env` 已经被提交到 git 了（安全问题）

我检查过：`git ls-files` 显示 `.env` **在版本控制里**。你的 MySQL 密码
已经进了 git 历史。

**要做的事**：
```bash
# 1) 把 .env 加进 .gitignore
echo ".env" >> .gitignore

# 2) 从 git 追踪中移除（但保留本地文件）
git rm --cached .env

# 3) 提交这个修复
git commit -m "chore: stop tracking .env, it contains credentials"
```

> ⚠️ 注意：这样做之后，**新的提交**不再包含 `.env`，但**旧的历史提交里还有**。
> 如果这个仓库推到了公开 GitHub，最稳妥的做法是**去 MySQL 改掉那个密码**。
> 如果仓库还没 push 过、或者是私有仓库且只有你自己，风险较低，改掉追踪即可。
>
> （彻底清除 git 历史需要 `git filter-repo` 之类的工具重写历史，属于破坏性操作，
> 要做之前先问清楚。）

#### 问题 2：`analytics.db` 没有被忽略

它是 ETL 生成的产物，不该进 git。

```bash
echo "analytics.db" >> .gitignore
echo ".DS_Store" >> .gitignore
```

#### 修好之后 `.gitignore` 应该长这样

```gitignore
# Python-generated files
__pycache__/
*.py[oc]
build/
dist/
wheels/
*.egg-info

# Virtual environments
.venv

# Secrets — 绝不提交
.env

# Generated artifacts
analytics.db
*.db

# macOS
.DS_Store
```

---

## 七、关键概念速查

### ORM 映射对照表

| 数据库（SQL） | Python（ORM） |
|---|---|
| 表 table | 类 class |
| 一行 row | 一个实例 object |
| 一列 column | 一个属性 attribute |
| 外键 foreign key | `relationship()` |

### SQLAlchemy 2.0 写法

```python
film_id: Mapped[int] = mapped_column(primary_key=True)   # 主键
title: Mapped[str]                                        # 普通列（NOT NULL）
length: Mapped[Optional[int]]                             # 可为 NULL 的列
language_id: Mapped[int] = mapped_column(ForeignKey("language.language_id"))  # 外键
language: Mapped[Language] = relationship()               # 关系（不是真实的列）
```

- **带 `mapped_column`** → 真实的数据库列
- **带 `relationship()`** → 只是 Python 层的「点号串联」语法糖，表里没有这一列

### 关系的三种形态

```python
# 多对一（子→父）：单个对象，写在有 ForeignKey 的那一边
language: Mapped["Language"] = relationship()

# 一对多（父→子）：list，写在没有 ForeignKey 的那一边
films: Mapped[list["Film"]] = relationship(back_populates="language")

# 多对多：list + secondary 指向中间表
actors: Mapped[list["Actor"]] = relationship(
    secondary="film_actor", back_populates="films"
)
```

> 引用「在后面才定义的类」时要加引号（前向引用），例如 `Mapped[list["Actor"]]`。

### 数据仓库术语

| 术语 | 含义 | 本项目的例子 |
|---|---|---|
| 维度表 dimension | 描述「名词/属性」 | `dim_film`、`dim_customer` |
| 事实表 fact | 记录「发生了什么」 | `fact_rental`、`fact_payment` |
| 桥接表 bridge | 维度之间的多对多 | `bridge_film_actor` |
| 代理键 surrogate key | 仓库自己生成的 ID | `film_key` |
| 自然键 natural key | 源库原本的 ID | `film_id` |
| 反规范化 denormalization | 提前 join 好，冗余换查询速度 | `dim_store` 直接存 `country` |
| 水位线 watermark | 「上次同步到哪了」 | `sync_state.last_update` |

### 为什么要反规范化

源库查「这次租借发生在哪个国家」要 join 5-6 张表：
```
payment → rental → inventory → store → address → city → country
```
分析库提前把 city/country 并进 `dim_store`，查询只要 join 2 次：
```sql
SELECT d.year, d.month, s.country, SUM(p.amount)
FROM fact_payment p
JOIN dim_date  d ON p.date_key_paid = d.date_key
JOIN dim_store s ON p.store_key     = s.store_key
GROUP BY d.year, d.month, s.country;
```

### 增量同步的原理

```python
# 1) 读上次的水位
state = t.get(SyncState, "film")
high_water = state.last_update          # 第一次是 1970-01-01

# 2) 只拉比水位新的行
new_rows = s.query(Film).filter(Film.last_update > high_water).all()

# 3) upsert 进目标表
# ...

# 4) 把水位推进到本次拉到的最大 last_update
state.last_update = max(r.last_update for r in new_rows)
t.commit()
```

> ⚠️ 推进水位要用「**本次实际拉到的最大 last_update**」，
> **不要用 `datetime.now()`** —— 否则 ETL 运行瞬间新写入的行会被误标为「已同步」，
> 下次就永久漏掉了。

### 为什么初始水位是 1970

`EPOCH = datetime(1970, 1, 1)` 是 Unix 纪元起点。用它当初始值，
第一次增量同步时 `last_update > 1970` 匹配所有行 → **自动退化成全量加载**，
不用为「第一次」写特殊逻辑。

---

## 八、明天怎么继续

### 环境确认（开工前先跑一遍）

```bash
cd /Users/wangying/Documents/GitHub/MPCS_Database/assignment4
uv run python -m src.cli init
# 应该 1 秒内输出 init completed
```

如果又卡住了 → 检查 `.venv` 软链接是否还在：
```bash
ls -la .venv
# 应该显示：.venv -> /Users/wangying/.venvs/assignment4
```

### 建议的任务顺序

1. **先修 git 卫生问题**（第六节的两个 `.gitignore` 修复）
2. **写 `full_load()`**
   - 从 `DimActor` 开始（最简单，无 join）
   - 再 `DimCategory`、`DimFilm`（join language）
   - 再 `DimStore`、`DimCustomer`（join address→city→country）
   - 再桥接表 `BridgeFilmActor`、`BridgeFilmCategory`
   - 最后事实表（要做自然键→代理键转换，最难）
3. **写 `incremental()`**（在 full_load 基础上加 WHERE 条件）
4. **写 `validate()`**（两边各跑聚合，比对结果）
5. **在 `cli.py` 里把这三个命令接上**

### 给新窗口 Claude 的开场白（可以直接复制）

```
我在做一个 MySQL(Sakila) → SQLite 的 ORM 数据同步作业。
请先读 assignment4/HANDOFF.md 了解背景和进度。

我是初学者，请像教授一样逐行解释代码，用中文讲解，
代码注释用英文的 docstring（三个双引号）格式。

今天要做的：写 sync.py 里的 full_load()，从最简单的 DimActor 开始。
```

---

## 九、今天学到的通用经验

1. **`KeyboardInterrupt` = 你自己按的 Ctrl+C**，不是程序崩溃。看到它要想「程序是卡住了」。
2. **排查卡顿用分层计时法**：裸 Python → 标准库 → 单个第三方包 → 完整程序，找出从哪层开始变慢。
3. **`real` 时间长 + `user` CPU 接近 0 = 在等外部资源**（磁盘、网络、系统服务），不是代码死循环。
4. **做决定性实验**：怀疑是位置问题，就在另一个位置建个一模一样的环境对比。一次实验胜过十次猜测。
5. **`~/Documents`、`~/Desktop` 不适合放开发项目** —— macOS 的 iCloud 同步会拖慢大量小文件的读取。推荐放 `~/dev/`、`~/code/` 这种普通目录。
6. **虚拟环境是产物不是资产** —— 可以随时删掉重建，所以永远不进 git。
7. **密码只进 `.env`，模板进 `.env.example`** —— `.env` 必须在 `.gitignore` 里，提交前务必确认。
8. **环境问题会掩盖代码问题** —— 今天的 `ImportError` 一直被卡顿挡着看不见。先把环境弄干净，错误信息才有意义。
