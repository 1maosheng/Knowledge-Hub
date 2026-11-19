<template>
  <div class="page">
    <div class="page-title">
      <div>
        <h2>知识图谱</h2>
        <div class="muted">实体与关系的结构化推理层（P1：LightRAG 抽取 → Neo4j 存储 → Cypher 模板查询）</div>
      </div>
      <el-tag type="warning" effect="plain">规划中</el-tag>
    </div>

    <div class="graph-canvas">
      <svg viewBox="0 0 900 420" style="width: 100%; height: 100%">
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="#9ca3af" />
          </marker>
        </defs>
        <g stroke="#cbd5e1" stroke-width="1.4" fill="none">
          <line x1="450" y1="210" x2="240" y2="120" marker-end="url(#arrow)" />
          <line x1="450" y1="210" x2="660" y2="120" marker-end="url(#arrow)" />
          <line x1="450" y1="210" x2="300" y2="330" marker-end="url(#arrow)" />
          <line x1="450" y1="210" x2="660" y2="320" marker-end="url(#arrow)" />
          <line x1="240" y1="120" x2="120" y2="210" marker-end="url(#arrow)" />
          <line x1="660" y1="320" x2="760" y2="230" marker-end="url(#arrow)" />
        </g>
        <g font-size="13" text-anchor="middle" font-family="PingFang SC, Microsoft YaHei, sans-serif">
          <g>
            <circle cx="450" cy="210" r="52" fill="#dbeafe" stroke="#93c5fd" />
            <text x="450" y="206" fill="#1e3a8a" font-weight="600">差旅报销</text>
            <text x="450" y="224" fill="#1e3a8a" font-size="11">Policy</text>
          </g>
          <g>
            <circle cx="240" cy="120" r="42" fill="#ede9fe" stroke="#c4b5fd" />
            <text x="240" y="125" fill="#4c1d95">一线城市</text>
          </g>
          <g>
            <circle cx="660" cy="120" r="42" fill="#ede9fe" stroke="#c4b5fd" />
            <text x="660" y="125" fill="#4c1d95">二线城市</text>
          </g>
          <g>
            <circle cx="300" cy="330" r="42" fill="#dcfce7" stroke="#86efac" />
            <text x="300" y="335" fill="#14532d">财务总监</text>
          </g>
          <g>
            <circle cx="660" cy="320" r="42" fill="#dcfce7" stroke="#86efac" />
            <text x="660" y="325" fill="#14532d">直属主管</text>
          </g>
          <g>
            <circle cx="120" cy="210" r="36" fill="#fff7ed" stroke="#fdba74" />
            <text x="120" y="215" fill="#9a3412" font-size="12">600 元/晚</text>
          </g>
          <g>
            <circle cx="760" cy="230" r="36" fill="#fff7ed" stroke="#fdba74" />
            <text x="760" y="235" fill="#9a3412" font-size="12">≤ 5000 元</text>
          </g>
        </g>
        <g fill="#6b7280" font-size="11" font-family="PingFang SC, Microsoft YaHei, sans-serif">
          <text x="300" y="165">住宿标准</text>
          <text x="570" y="150">住宿标准</text>
          <text x="345" y="285">审批人</text>
          <text x="570" y="285">审批人</text>
          <text x="150" y="175">金额</text>
          <text x="720" y="285">阈值</text>
        </g>
      </svg>
      <div class="graph-empty" style="align-items: flex-end; padding-bottom: 20px">
        <el-alert type="info" :closable="false" show-icon
          title="P0 阶段图谱为示意；P1 将提供文档自动抽取、实体对齐、子图查询与 G6 交互式可视化" />
      </div>
    </div>
  </div>
</template>