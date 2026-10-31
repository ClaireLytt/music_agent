# 规格：数据备份与恢复（导入导出）

状态：已评审（2026-10-30 grill 轮定稿）。参考实现调研见
docs/research_ipad_and_import_export.md 与 qwerty-learner 的
src/utils/db/data-export.ts（替换式导入 + 进度条 + 红字警告的 UX 来源）。

## 目标

防止换电脑丢数据；为后续公网演示提供"部署时初始化数据"的素材。
**不做**：选择性导出、合并导入、多设备同步。

## 行为规格

### 导出（GET /api/backup/export）
- 打包整个 `data/` 为 zip 流式下载，文件名 `lyric_lens_backup_<YYYY-MM-DD>.zip`。
- zip 内部保持 `data/` 原目录结构（手动解压覆盖也能用——逃生通道）。
- **key 剥离**：`user_settings.json` 在包内的副本删除 `api_key` 字段，其余字段保留。
- 除 key 外全包：mp3、AI 缓存、TTS 缓存（data/cache/）、卡片图（data/cards/）等
  可再生数据一律带上。
- public 模式：403。

### 导入（POST /api/backup/import，multipart zip）
- 语义 = **清空替换**（同 qwerty-learner `clearTablesBeforeImport`）：
  1. 校验 zip（能解开、顶层结构像 data/：至少含 songs/ 或 wordbook.json 之一，防传错文件）；
  2. 现有 `data/` 整体改名留底 `data.bak_<时间戳>/`；
  3. zip 解包为新 `data/`；
  4. 包内 `user_settings.json` 若带 `api_key`，**不写入**（保留本机现值：从留底拷回该字段）。
- 失败回滚：任一步失败，把留底改回 `data/`，返回错误。
- public 模式：403。

### 写闸门（前置安全项）
- API 层新增统一 public 检查依赖（此前只有旧 Gradio 层有，见调研文档），
  本功能两个端点必须挂上；其余已有写端点一并挂（同一个 PR 内做完）。

### UI（设置页「数据备份」区块）
- 「导出全部数据 (zip)」下载按钮 + 「从备份恢复」上传框。
- 恢复需二次确认；红字说明：将替换当前全部数据、原数据留底于 data.bak_*、
  请勿修改备份文件内容（文案参考 qwerty-learner）。
- 导入中显示进度/禁用按钮；完成后提示刷新。
- public 模式整块隐藏（服务端 403 为准，前端隐藏只是体验）。

## 验收标准（全过才算完成）

1. roundtrip：导出 → 删 `data/` → 导入 → 收藏数/单词数/打字热力图/mp3 可播
   与导出前一致。
2. 导出包内任何文件搜不到本机 `api_key` 的值。
3. 导入后旧数据存在于 `data.bak_<时间戳>/`；导入失败时 `data/` 完好如初。
4. public 模式下两个端点返回 403；设置页不显示该区块。
5. `python -m pytest tests/ -q` 全绿；`python scripts/ui_probe.py` 全绿。

## 任务分工（可独立领取，按序号依赖）

| # | 任务 | 文件 | 依赖 |
|---|---|---|---|
| T1 | public 写闸门依赖（FastAPI dependency）+ 挂到现有写端点 | src/lyric_agent/api.py | 无 |
| T2 | 导出端点：zip 流 + key 剥离 | src/lyric_agent/api.py（新 backup 段） | T1 |
| T3 | 导入端点：校验→留底→解包→key 保留→回滚 | 同上 | T1 |
| T4 | 单测：剥离/留底/回滚/403/roundtrip（tmp 目录造最小 data/） | tests/test_backup.py | T2 T3 |
| T5 | 设置页 UI 区块（按钮/上传/确认/进度/public 隐藏） | frontend/src/pages/SettingsPage.tsx, api.ts | T2 T3 |
| T6 | 真实 roundtrip 手测 + ui_probe 回归 | — | T1–T5 |
