# 喜鹊儿课表导出工具

基于 `Python + tkinter` 的课表导出工具，可自定义导出 `CSV` 文件和 `ICS` 日历文件。

## 环境要求

- Python 3.10+
- 依赖：
  - `requests`
  - `cryptography`
  - `tkinter`（通常 Python 自带）

安装依赖：

```bash
pip install requests cryptography
```

## 运行

```bash
python xiqueer_timetable.py
```

## 使用说明

1. 填写学校、账号、密码
2. 选择学期模式（默认“当前”，也可切到“特定”后手动勾选学期）
3. 选择输出路径
4. 选择是否导出 ICS
5. 需要时调整 CSV / ICS 字段
6. 点击“开始导出”


## 字段说明（原始名称）

下表中的“原始名称”就是代码和导出配置里使用的字段 key。

| 原始名称 | 中文列名 | 含义 |
| --- | --- | --- |
| `school_name` | 学校名称 | 当前登录学校名称 |
| `school_code` | 学校代码 | 当前学校代码 |
| `account` | 账号 | 登录账号 |
| `user_id` | 用户ID | 接口返回的用户标识 |
| `term_code` | 学期代码 | 学期编码 |
| `term_name` | 学期名称 | 学期名称 |
| `weekday_num` | 星期序号 | 周几序号（1-7） |
| `weekday_name` | 星期 | 周几名称（星期一等） |
| `course_name` | 课程名称 | 课程名称 |
| `teacher` | 教师 | 任课教师 |
| `location` | 上课地点 | 上课地点 |
| `campus` | 校区 | 所属校区 |
| `teaching_class` | 教学班 | 教学班名称 |
| `teaching_class_code` | 教学班代码 | 教学班编码 |
| `course_code` | 课程代码 | 课程编码 |
| `course_alias_code` | 课程别名代码 | 课程别名编码 |
| `credits` | 学分 | 学分值 |
| `weeks` | 上课周次 | 原始周次文本（如 1-16周） |
| `sections` | 节次 | 原始节次文本 |
| `section_codes` | 节次代码 | 节次编码 |
| `time_source` | 时间来源 | 使用的作息来源（教务/个人/合并） |
| `period_sections` | 解析节次 | 解析后的节次编号列表 |
| `period_start` | 开始时间 | 节次对应开始时间 |
| `period_end` | 结束时间 | 节次对应结束时间 |
| `period_duration_min` | 时长(分钟) | 节次时长（分钟） |
| `period_note` | 时间备注 | 时间解析备注信息 |
| `student_count` | 人数 | 课程人数 |
| `remark` | 备注 | 备注信息 |
| `live_url` | 直播链接 | 课程直播链接 |
| `start_time` | 接口开始时间 | 接口返回开始时间字段 |
| `end_time` | 接口结束时间 | 接口返回结束时间字段 |
| `date` | 接口日期 | 接口返回日期字段 |

---
