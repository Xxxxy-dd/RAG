import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, App as AntApp, Button, Card, Col, Collapse, ConfigProvider, Divider, Form, Input, Row, Space, Spin, Switch, Tag, Typography, message } from 'antd';
import { askQuestion, clearSession, getSessionMessages, type SessionMessage } from './api';
import type { QAResponse } from './types';
import './styles.css';

const { Title, Paragraph, Text } = Typography;

const SESSION_SUMMARIES_STORAGE_KEY = 'rag_session_summaries';
const ACTIVE_SESSION_STORAGE_KEY = 'rag_session_id';
const SIDEBAR_COLLAPSED_STORAGE_KEY = 'rag_sidebar_collapsed';

interface SessionSummary {
  session_id: string;
  title: string;
  preview: string;
  updated_at: string;
  turn_count: number;
}

function formatSessionTimestamp(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function createSessionId(): string {
  const prefix = `sess-${formatSessionTimestamp(new Date())}`;
  const suffix = window.crypto?.getRandomValues
    ? Array.from(window.crypto.getRandomValues(new Uint8Array(3)), (value) => value.toString(16).padStart(2, '0')).join('')
    : Math.random().toString(16).slice(2, 8);
  return `${prefix}-${suffix}`;
}

function getOrCreateSessionId(): string {
  const existing = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
  if (existing) return existing;
  const created = createSessionId();
  window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, created);
  return created;
}

function getInitialSidebarCollapsed(): boolean {
  return window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === 'true';
}

function shorten(text: string, maxLength: number): string {
  const normalized = text.replace(/\s+/g, ' ').trim();
  if (!normalized) return '';
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 1)}…` : normalized;
}

function compareSessionSummaries(a: SessionSummary, b: SessionSummary): number {
  return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime() || b.turn_count - a.turn_count || a.title.localeCompare(b.title, 'zh-Hans-CN');
}

function readSessionSummaries(): SessionSummary[] {
  try {
    const raw = window.localStorage.getItem(SESSION_SUMMARIES_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is SessionSummary => item && typeof item.session_id === 'string')
      .map((item) => ({
        session_id: item.session_id,
        title: typeof item.title === 'string' && item.title.trim() ? item.title : '新对话',
        preview: typeof item.preview === 'string' ? item.preview : '',
        updated_at: typeof item.updated_at === 'string' ? item.updated_at : new Date().toISOString(),
        turn_count: typeof item.turn_count === 'number' ? item.turn_count : 0,
      }))
      .sort(compareSessionSummaries);
  } catch {
    return [];
  }
}

function writeSessionSummaries(items: SessionSummary[]): void {
  window.localStorage.setItem(SESSION_SUMMARIES_STORAGE_KEY, JSON.stringify(items));
}

function summarizeSession(
  sessionId: string,
  messages: SessionMessage[],
  existing: SessionSummary | null,
  fallbackTitle: string,
  fallbackPreview: string,
): SessionSummary {
  const userMessages = messages.filter((message) => message.role === 'user');
  const assistantMessages = messages.filter((message) => message.role === 'assistant');
  const firstUserMessage = userMessages[0]?.text || '';
  const lastUserMessage = userMessages[userMessages.length - 1]?.text || '';
  const lastAssistantMessage = assistantMessages[assistantMessages.length - 1]?.text || '';
  const titleSource = firstUserMessage || existing?.title || fallbackTitle;
  const previewSource = lastAssistantMessage || lastUserMessage || existing?.preview || fallbackPreview;

  return {
    session_id: sessionId,
    title: shorten(titleSource, 28),
    preview: shorten(previewSource, 48),
    updated_at: new Date().toISOString(),
    turn_count: userMessages.length,
  };
}

function formatSessionTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export default function App() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [result, setResult] = useState<QAResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState(() => getOrCreateSessionId());
  const [sessionMessages, setSessionMessages] = useState<SessionMessage[]>([]);
  const [sessionSummaries, setSessionSummaries] = useState<SessionSummary[]>(() => readSessionSummaries());
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => getInitialSidebarCollapsed());
  const feedEndRef = useRef<HTMLDivElement | null>(null);

  const activeSessionSummary = useMemo(
    () => sessionSummaries.find((item) => item.session_id === sessionId) ?? null,
    [sessionSummaries, sessionId],
  );

  const orderedSessions = useMemo(() => [...sessionSummaries].sort(compareSessionSummaries), [sessionSummaries]);
  const activeSessionItems = useMemo(
    () => orderedSessions.filter((item) => item.session_id === sessionId),
    [orderedSessions, sessionId],
  );
  const recentSessionItems = useMemo(
    () => orderedSessions.filter((item) => item.session_id !== sessionId),
    [orderedSessions, sessionId],
  );

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  function ensureSummaryExists(sessionIdentifier: string, fallbackTitle = '新对话', fallbackPreview = '等待你输入第一条问题'): void {
    setSessionSummaries((current) => {
      if (current.some((item) => item.session_id === sessionIdentifier)) {
        return current;
      }
      const next = summarizeSession(sessionIdentifier, [], null, fallbackTitle, fallbackPreview);
      const updated = [...current, next].sort(compareSessionSummaries);
      writeSessionSummaries(updated);
      return updated;
    });
  }

  function updateSummaryFromMessages(
    sessionIdentifier: string,
    messages: SessionMessage[],
    fallbackTitle = '新对话',
    fallbackPreview = '等待你输入第一条问题',
  ): void {
    setSessionSummaries((current) => {
      const existing = current.find((item) => item.session_id === sessionIdentifier) ?? null;
      const next = summarizeSession(sessionIdentifier, messages, existing, fallbackTitle, fallbackPreview);
      const updated = [...current.filter((item) => item.session_id !== sessionIdentifier), next].sort(compareSessionSummaries);
      writeSessionSummaries(updated);
      return updated;
    });
  }

  async function loadSessionHistory(
    nextSessionId: string,
    options?: {
      fallbackTitle?: string;
      fallbackPreview?: string;
    },
  ) {
    if (!nextSessionId) {
      setSessionMessages([]);
      return;
    }

    try {
      setLoadingHistory(true);
      const data = await getSessionMessages(nextSessionId, 20);
      setSessionMessages(data.messages);
      updateSummaryFromMessages(
        nextSessionId,
        data.messages,
        options?.fallbackTitle ?? '新对话',
        options?.fallbackPreview ?? '等待你输入第一条问题',
      );
    } catch (err) {
      setSessionMessages([]);
      message.error(err instanceof Error ? err.message : '加载会话历史失败');
    } finally {
      setLoadingHistory(false);
    }
  }

  function regenerateSessionId() {
    const nextSessionId = createSessionId();
    window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, nextSessionId);
    setSessionId(nextSessionId);
    setSessionMessages([]);
    setResult(null);
    setError(null);
    ensureSummaryExists(nextSessionId, '新对话', '等待你输入第一条问题');
  }

  function startNewConversation() {
    regenerateSessionId();
    form.setFieldsValue({ question: '' });
  }

  function toggleSidebar() {
    setSidebarCollapsed((current) => !current);
  }

  async function onClearSession() {
    if (!sessionId) return;
    try {
      setLoading(true);
      await clearSession(sessionId);
      message.success('已清空会话短期记忆');
      setSessionMessages([]);
      setResult(null);
      await loadSessionHistory(sessionId, {
        fallbackTitle: activeSessionSummary?.title || '新对话',
        fallbackPreview: '已清空会话',
      });
    } catch (err) {
      message.error(err instanceof Error ? err.message : '清空会话失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    form.setFieldsValue({
      top_k: 6,
      top_n: 4,
      use_query_rewrite: true,
      collection_name: 'document_indexing',
      persist_directory: '',
    });
  }, [form]);

  useEffect(() => {
    const storedSummaries = readSessionSummaries();
    if (storedSummaries.length > 0) {
      const merged = storedSummaries.some((item) => item.session_id === sessionId)
        ? storedSummaries
        : [...storedSummaries, summarizeSession(sessionId, [], null, '新对话', '等待你输入第一条问题')];
      const sorted = [...merged].sort(compareSessionSummaries);
      writeSessionSummaries(sorted);
      setSessionSummaries(sorted);
    } else {
      const initial = summarizeSession(sessionId, [], null, '新对话', '等待你输入第一条问题');
      writeSessionSummaries([initial]);
      setSessionSummaries([initial]);
    }

    void loadSessionHistory(sessionId, {
      fallbackTitle: '新对话',
      fallbackPreview: '等待你输入第一条问题',
    });
  }, [sessionId]);

  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [sessionMessages, result, loadingHistory, loading]);

  async function onFinish(values: Record<string, unknown>) {
    setLoading(true);
    setError(null);
    try {
      const payload = {
        question: String(values.question || '').trim(),
        session_id: sessionId,
        top_k: Number(values.top_k || 6),
        top_n: Number(values.top_n || 4),
        use_query_rewrite: Boolean(values.use_query_rewrite),
        collection_name: String(values.collection_name || 'document_indexing'),
        persist_directory: values.persist_directory ? String(values.persist_directory) : null,
      };
      const data = await askQuestion(payload);
      setResult(data);
      form.setFieldsValue({ question: '' });
      await loadSessionHistory(payload.session_id, {
        fallbackTitle: String(values.question || '新对话'),
        fallbackPreview: data.answer,
      });
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : '未知错误');
    } finally {
      setLoading(false);
    }
  }

  function handleSwitchSession(targetSessionId: string) {
    if (!targetSessionId || targetSessionId === sessionId) return;
    window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, targetSessionId);
    setSessionId(targetSessionId);
    setResult(null);
    setError(null);
  }

  async function exportSession(format: 'json' | 'md') {
    try {
      setLoadingHistory(true);
      const data = await getSessionMessages(sessionId, 200);
      if (format === 'json') {
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${sessionId}-messages.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        return;
      }

      const lines: string[] = [];
      lines.push(`# Session ${data.session_id}\n`);
      for (const messageItem of data.messages) {
        lines.push(`- **${messageItem.role}** #{${messageItem.seq}} _${messageItem.created_at}_`);
        lines.push('');
        lines.push(messageItem.text || '');
        lines.push('');
      }
      const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${sessionId}-messages.md`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '导出失败');
    } finally {
      setLoadingHistory(false);
    }
  }

  const visibleMessages = sessionMessages.filter((item) => item.role === 'user' || item.role === 'assistant');

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#10a37f',
          borderRadius: 18,
          fontFamily: 'Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        },
      }}
    >
      <AntApp>
        <div className="chat-shell">
          <aside className={`chat-sidebar ${sidebarCollapsed ? 'chat-sidebar-collapsed' : ''}`}>
            <div className="sidebar-header">
              {!sidebarCollapsed && (
                <div>
                  <Title level={4} style={{ margin: 0, color: '#111827' }}>
                    RAG QA Demo
                  </Title>
                  <Paragraph style={{ margin: '6px 0 0', color: '#6b7280' }}>
                    左侧历史会话，右侧当前对话
                  </Paragraph>
                </div>
              )}

              <Space direction={sidebarCollapsed ? 'vertical' : 'horizontal'} style={{ width: '100%' }}>
                <Button type="primary" block onClick={startNewConversation}>
                  {sidebarCollapsed ? '新' : '新对话'}
                </Button>
                <Button block onClick={toggleSidebar}>
                  {sidebarCollapsed ? '展开' : '收起'}
                </Button>
              </Space>
            </div>

            <div className={`sidebar-list ${sidebarCollapsed ? 'sidebar-list-collapsed' : ''}`}>
              {!sidebarCollapsed && (
                <div className="session-section">
                  <div className="session-section-header">
                    <span className="section-icon section-icon-active">◎</span>
                    <Text strong style={{ color: '#111827' }}>
                      当前会话
                    </Text>
                  </div>

                  {activeSessionItems.length === 0 ? (
                    <div className="sidebar-empty sidebar-empty-compact">
                      <Title level={5} style={{ color: '#111827', marginTop: 0 }}>
                        新对话
                      </Title>
                      <Paragraph style={{ color: '#6b7280', marginBottom: 0 }}>
                        当前会话还没有可显示的标题。
                      </Paragraph>
                    </div>
                  ) : (
                    activeSessionItems.map((item) => (
                      <button
                        key={item.session_id}
                        type="button"
                        className={`session-card session-card-active ${sessionId === item.session_id ? 'session-card-selected' : ''}`}
                        onClick={() => handleSwitchSession(item.session_id)}
                      >
                        <div className="session-card-top">
                          <div className="session-card-title-wrap">
                            <span className="session-card-icon session-card-icon-current">◉</span>
                            <Text className="session-title">{item.title}</Text>
                          </div>
                          <Tag color="green">当前</Tag>
                        </div>
                        <Paragraph className="session-preview">{item.preview || '暂无预览'}</Paragraph>
                        <div className="session-card-meta">
                          <Text type="secondary">{formatSessionTime(item.updated_at)}</Text>
                          <Text type="secondary">{item.turn_count} 轮</Text>
                        </div>
                      </button>
                    ))
                  )}
                </div>
              )}

              {!sidebarCollapsed && recentSessionItems.length > 0 && (
                <div className="session-section">
                  <div className="session-section-header">
                    <span className="section-icon section-icon-recent">☰</span>
                    <Text strong style={{ color: '#111827' }}>
                      最近会话
                    </Text>
                  </div>
                </div>
              )}

              {sidebarCollapsed ? (
                orderedSessions.length === 0 ? (
                  <div className="sidebar-empty sidebar-empty-collapsed" />
                ) : (
                  orderedSessions.map((item) => {
                    const active = item.session_id === sessionId;
                    return (
                      <button
                        key={item.session_id}
                        type="button"
                        className={`session-card ${active ? 'session-card-active' : ''}`}
                        onClick={() => handleSwitchSession(item.session_id)}
                      >
                        <div className="session-card-collapsed-dot" title={item.title}>
                          <span />
                        </div>
                      </button>
                    );
                  })
                )
              ) : recentSessionItems.length === 0 ? (
                <div className="sidebar-empty">
                  <Title level={5} style={{ color: '#111827', marginTop: 0 }}>
                    还没有历史会话
                  </Title>
                  <Paragraph style={{ color: '#6b7280', marginBottom: 0 }}>
                    你发送第一条问题后，会在这里自动生成历史记录。
                  </Paragraph>
                </div>
              ) : (
                recentSessionItems.map((item) => {
                  return (
                    <button
                      key={item.session_id}
                      type="button"
                      className="session-card"
                      onClick={() => handleSwitchSession(item.session_id)}
                    >
                      <div className="session-card-top">
                        <div className="session-card-title-wrap">
                          <span className="session-card-icon">◔</span>
                          <Text className="session-title">{item.title}</Text>
                        </div>
                        <Tag color="default">历史</Tag>
                      </div>
                      <Paragraph className="session-preview">{item.preview || '暂无预览'}</Paragraph>
                      <div className="session-card-meta">
                        <Text type="secondary">{formatSessionTime(item.updated_at)}</Text>
                        <Text type="secondary">{item.turn_count} 轮</Text>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </aside>

          <main className="chat-main">
            <header className="chat-topbar">
              <div>
                <Title level={3} style={{ margin: 0, color: '#111827' }}>
                  {activeSessionSummary?.title || '新对话'}
                </Title>
                <Space size={8} wrap style={{ marginTop: 10 }}>
                  <Tag color="default">session: {sessionId.slice(0, 8)}</Tag>
                  <Tag color="default">{activeSessionSummary?.turn_count ?? 0} 轮</Tag>
                  <Tag color="default">{sessionMessages.length} 条消息</Tag>
                </Space>
              </div>

              <Space wrap>
                <Button onClick={() => exportSession('json')} loading={loadingHistory}>
                  导出 JSON
                </Button>
                <Button onClick={() => exportSession('md')} loading={loadingHistory}>
                  导出 Markdown
                </Button>
                <Button danger onClick={onClearSession} loading={loading}>
                  清空会话
                </Button>
              </Space>
            </header>

            <section className="chat-stream">
              <div className="chat-feed">
                {loadingHistory ? (
                  <div className="loading-box chat-loading">
                    <Spin size="large" />
                    <Text>正在加载当前会话历史...</Text>
                  </div>
                ) : visibleMessages.length === 0 ? (
                  <div className="empty-state chat-empty">
                    <Title level={4} style={{ color: '#111827', marginTop: 0 }}>
                      准备开始
                    </Title>
                    <Paragraph style={{ color: '#6b7280', marginBottom: 0 }}>
                      这里会显示你和模型的完整对话记录。你可以在底部输入问题，右侧会像大语言模型网页一样持续展开消息。
                    </Paragraph>
                  </div>
                ) : (
                  visibleMessages.map((item) => {
                    const isUser = item.role === 'user';
                    return (
                      <div key={item.message_id} className={`message-row ${isUser ? 'message-row-user' : 'message-row-assistant'}`}>
                        {!isUser && <div className="message-avatar assistant-avatar">AI</div>}
                        <div className={`message-bubble ${isUser ? 'message-bubble-user' : 'message-bubble-assistant'}`}>
                          <div className="message-meta">
                            <span className={`message-role-chip ${isUser ? 'message-role-chip-user' : 'message-role-chip-assistant'}`}>
                              {isUser ? '你' : '助手'}
                            </span>
                            <Text type="secondary" style={{ marginLeft: 8 }}>
                              #{item.seq}
                            </Text>
                            <Text type="secondary" style={{ marginLeft: 8 }}>
                              {item.created_at}
                            </Text>
                          </div>
                          <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{item.text}</Paragraph>
                        </div>
                        {isUser && <div className="message-avatar user-avatar">我</div>}
                      </div>
                    );
                  })
                )}

                {loading && (
                  <div className="message-row message-row-assistant typing-row">
                    <div className="message-avatar assistant-avatar">AI</div>
                    <div className="message-bubble message-bubble-assistant typing-bubble">
                      <div className="message-meta">
                        <span className="message-role-chip message-role-chip-assistant">助手</span>
                        <Text type="secondary" style={{ marginLeft: 8 }}>
                          正在生成
                        </Text>
                      </div>
                      <div className="typing-dots" aria-label="正在生成回答">
                        <span />
                        <span />
                        <span />
                      </div>
                      <Text type="secondary" style={{ display: 'block', marginTop: 10 }}>
                        正在检索知识库并组织回答...
                      </Text>
                    </div>
                  </div>
                )}

                {error && <Alert className="result-alert" type="error" showIcon message="请求失败" description={error} />}

                {result && (
                  <Card className="result-insight-card" bordered={false}>
                    <Title level={5} style={{ marginTop: 0 }}>
                      本次回答详情
                    </Title>
                    <Card size="small" className="insight-block">
                      <Text strong>原始问题：</Text>
                      <Paragraph style={{ marginTop: 8, marginBottom: 0, whiteSpace: 'pre-wrap' }}>{result.question}</Paragraph>
                      <Divider style={{ margin: '14px 0' }} />
                      <Text strong>改写查询：</Text>
                      <Paragraph style={{ marginTop: 8, marginBottom: 0, whiteSpace: 'pre-wrap' }}>{result.rewritten_question}</Paragraph>
                    </Card>

                    <Card size="small" className="insight-block" style={{ marginTop: 16 }}>
                      <Text strong>回答：</Text>
                      <Paragraph style={{ marginTop: 8, marginBottom: 0, whiteSpace: 'pre-wrap' }}>{result.answer}</Paragraph>
                    </Card>

                    <Card size="small" className="insight-block" style={{ marginTop: 16 }}>
                      <Text strong>引用上下文：</Text>
                      <div style={{ marginTop: 12 }}>
                        {result.contexts.length === 0 ? (
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                            没有返回上下文。
                          </Paragraph>
                        ) : (
                          result.contexts.map((item) => (
                            <Card key={item.index} size="small" style={{ marginBottom: 12 }}>
                              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                                <Text strong>片段 {item.index}</Text>
                                <Text type="secondary">{item.title_path || 'ROOT'}</Text>
                                <Text type="secondary">来源：{item.source || 'unknown'}</Text>
                                <Text type="secondary">
                                  retrieval: {item.retrieval_score ?? '-'} | rerank: {item.rerank_score ?? '-'}
                                </Text>
                                <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{item.text}</Paragraph>
                              </Space>
                            </Card>
                          ))
                        )}
                      </div>
                    </Card>
                  </Card>
                )}

                <div ref={feedEndRef} />
              </div>
            </section>

            <section className="composer-shell">
              <div className="composer-inner">
                <Form form={form} layout="vertical" onFinish={onFinish} initialValues={{ question: '' }}>
                  <Form.Item name="question" label={null} rules={[{ required: true, message: '请输入问题' }]}>
                    <Input.TextArea
                      autoSize={{ minRows: 3, maxRows: 7 }}
                      placeholder="输入你的问题，按 Ctrl/⌘ + Enter 发送，像大语言模型网页一样开始对话"
                      onKeyDown={(event) => {
                        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
                          event.preventDefault();
                          form.submit();
                        }
                      }}
                    />
                  </Form.Item>

                  <div className="composer-actions">
                    <Text type="secondary">当前 session：{sessionId.slice(0, 8)}</Text>
                    <Button type="primary" htmlType="submit" loading={loading} size="large">
                      发送
                    </Button>
                  </div>

                  <Collapse
                    ghost
                    className="advanced-collapse"
                    items={[
                      {
                        key: 'advanced',
                        label: '高级设置',
                        children: (
                          <Row gutter={12}>
                            <Col xs={12} sm={6}>
                              <Form.Item name="top_k" label="检索候选数">
                                <Input type="number" min={1} max={50} />
                              </Form.Item>
                            </Col>
                            <Col xs={12} sm={6}>
                              <Form.Item name="top_n" label="重排保留数">
                                <Input type="number" min={1} max={20} />
                              </Form.Item>
                            </Col>
                            <Col xs={24} sm={6}>
                              <Form.Item name="collection_name" label="Chroma 集合名">
                                <Input />
                              </Form.Item>
                            </Col>
                            <Col xs={24} sm={6}>
                              <Form.Item name="persist_directory" label="持久化目录">
                                <Input placeholder="默认使用 rag/indexes/chroma_db" />
                              </Form.Item>
                            </Col>
                            <Col xs={24}>
                              <Form.Item name="use_query_rewrite" label="启用查询改写" valuePropName="checked">
                                <Switch />
                              </Form.Item>
                            </Col>
                          </Row>
                        ),
                      },
                    ]}
                  />
                </Form>
              </div>
            </section>
          </main>
        </div>
      </AntApp>
    </ConfigProvider>
  );
}