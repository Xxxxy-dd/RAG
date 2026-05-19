import {
  ClearOutlined,
  DownloadOutlined,
  FileMarkdownOutlined,
  HistoryOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MessageOutlined,
  PlusOutlined,
  RobotOutlined,
  SendOutlined,
  UserOutlined,
} from '@ant-design/icons';
import {
  Alert,
  App as AntApp,
  Button,
  ConfigProvider,
  Form,
  Input,
  Segmented,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';

import { askQuestion, clearSession, getSessionMessages, type SessionMessage } from './api';
import type { QAResponse } from './types';
import './styles.css';

const { Paragraph, Text, Title } = Typography;

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
    ? Array.from(window.crypto.getRandomValues(new Uint8Array(3)), (value) =>
        value.toString(16).padStart(2, '0'),
      ).join('')
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
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 1)}...` : normalized;
}

function compareSessionSummaries(a: SessionSummary, b: SessionSummary): number {
  return (
    new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime() ||
    b.turn_count - a.turn_count ||
    a.title.localeCompare(b.title, 'zh-Hans-CN')
  );
}

function normalizeSummary(item: Partial<SessionSummary>): SessionSummary | null {
  if (!item || typeof item.session_id !== 'string') return null;
  return {
    session_id: item.session_id,
    title: typeof item.title === 'string' && item.title.trim() ? item.title : '新对话',
    preview: typeof item.preview === 'string' ? item.preview : '',
    updated_at: typeof item.updated_at === 'string' ? item.updated_at : new Date().toISOString(),
    turn_count: typeof item.turn_count === 'number' ? item.turn_count : 0,
  };
}

function readSessionSummaries(): SessionSummary[] {
  try {
    const raw = window.localStorage.getItem(SESSION_SUMMARIES_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item) => normalizeSummary(item))
      .filter((item): item is SessionSummary => item !== null)
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
  const userMessages = messages.filter((item) => item.role === 'user');
  const assistantMessages = messages.filter((item) => item.role === 'assistant');
  const firstUserMessage = userMessages[0]?.text || '';
  const lastUserMessage = userMessages[userMessages.length - 1]?.text || '';
  const lastAssistantMessage = assistantMessages[assistantMessages.length - 1]?.text || '';

  return {
    session_id: sessionId,
    title: shorten(firstUserMessage || existing?.title || fallbackTitle, 30),
    preview: shorten(lastAssistantMessage || lastUserMessage || existing?.preview || fallbackPreview, 56),
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

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
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
  const [exportFormat, setExportFormat] = useState<'json' | 'md'>('md');
  const feedEndRef = useRef<HTMLDivElement | null>(null);

  const activeSessionSummary = useMemo(
    () => sessionSummaries.find((item) => item.session_id === sessionId) ?? null,
    [sessionSummaries, sessionId],
  );

  const orderedSessions = useMemo(() => [...sessionSummaries].sort(compareSessionSummaries), [sessionSummaries]);
  const visibleMessages = sessionMessages.filter((item) => item.role === 'user' || item.role === 'assistant');

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  function ensureSummaryExists(sessionIdentifier: string, fallbackTitle = '新对话', fallbackPreview = '等待输入第一条问题'): void {
    setSessionSummaries((current) => {
      if (current.some((item) => item.session_id === sessionIdentifier)) return current;
      const updated = [
        ...current,
        summarizeSession(sessionIdentifier, [], null, fallbackTitle, fallbackPreview),
      ].sort(compareSessionSummaries);
      writeSessionSummaries(updated);
      return updated;
    });
  }

  function updateSummaryFromMessages(
    sessionIdentifier: string,
    messages: SessionMessage[],
    fallbackTitle = '新对话',
    fallbackPreview = '等待输入第一条问题',
  ): void {
    setSessionSummaries((current) => {
      const existing = current.find((item) => item.session_id === sessionIdentifier) ?? null;
      const next = summarizeSession(sessionIdentifier, messages, existing, fallbackTitle, fallbackPreview);
      const updated = [...current.filter((item) => item.session_id !== sessionIdentifier), next].sort(
        compareSessionSummaries,
      );
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
      const data = await getSessionMessages(nextSessionId, 40);
      setSessionMessages(data.messages);
      updateSummaryFromMessages(
        nextSessionId,
        data.messages,
        options?.fallbackTitle ?? '新对话',
        options?.fallbackPreview ?? '等待输入第一条问题',
      );
    } catch (err) {
      setSessionMessages([]);
      message.error(err instanceof Error ? err.message : '加载会话历史失败');
    } finally {
      setLoadingHistory(false);
    }
  }

  function startNewConversation() {
    const nextSessionId = createSessionId();
    window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, nextSessionId);
    setSessionId(nextSessionId);
    setSessionMessages([]);
    setResult(null);
    setError(null);
    form.setFieldsValue({ question: '' });
    ensureSummaryExists(nextSessionId);
  }

  async function onClearSession() {
    if (!sessionId) return;
    try {
      setLoading(true);
      await clearSession(sessionId);
      message.success('已清空当前会话');
      setSessionMessages([]);
      setResult(null);
      await loadSessionHistory(sessionId, {
        fallbackTitle: activeSessionSummary?.title || '新对话',
        fallbackPreview: '当前会话已清空',
      });
    } catch (err) {
      message.error(err instanceof Error ? err.message : '清空会话失败');
    } finally {
      setLoading(false);
    }
  }

  async function exportSession() {
    try {
      setLoadingHistory(true);
      const data = await getSessionMessages(sessionId, 200);
      if (exportFormat === 'json') {
        downloadBlob(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }), `${sessionId}.json`);
        return;
      }

      const lines: string[] = [`# ${activeSessionSummary?.title || data.session_id}`, ''];
      for (const item of data.messages) {
        lines.push(`## ${item.role} #${item.seq}`);
        lines.push('');
        lines.push(item.text || '');
        lines.push('');
      }
      downloadBlob(new Blob([lines.join('\n')], { type: 'text/markdown' }), `${sessionId}.md`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '导出失败');
    } finally {
      setLoadingHistory(false);
    }
  }

  useEffect(() => {
    form.setFieldsValue({
      question: '',
    });
  }, [form]);

  useEffect(() => {
    const storedSummaries = readSessionSummaries();
    const hasSession = storedSummaries.some((item) => item.session_id === sessionId);
    const summaries = hasSession
      ? storedSummaries
      : [...storedSummaries, summarizeSession(sessionId, [], null, '新对话', '等待输入第一条问题')];
    const sorted = summaries.sort(compareSessionSummaries);
    writeSessionSummaries(sorted);
    setSessionSummaries(sorted);

    void loadSessionHistory(sessionId);
  }, [sessionId]);

  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [sessionMessages, result, loadingHistory, loading]);

  async function onFinish(values: Record<string, unknown>) {
    const question = String(values.question || '').trim();
    if (!question) return;

    setLoading(true);
    setError(null);
    try {
      const payload = {
        question,
        session_id: sessionId,
      };
      const data = await askQuestion(payload);
      setResult(data);
      form.setFieldsValue({ question: '' });
      await loadSessionHistory(payload.session_id, {
        fallbackTitle: question,
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

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#5f6368',
          borderRadius: 8,
          colorBgLayout: '#ffffff',
          colorBorder: '#e5e5e5',
          colorText: '#1f1f1f',
          colorTextSecondary: '#8a8a8a',
          fontFamily:
            'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        },
      }}
    >
      <AntApp>
        <div className="workspace-shell">
          <aside className={`workspace-sidebar ${sidebarCollapsed ? 'is-collapsed' : ''}`}>
            <div className="sidebar-titlebar">
              {!sidebarCollapsed && (
                <div className="brand-lockup">
                  <div className="brand-mark">R</div>
                  <div>
                    <Text className="brand-title">知识问答</Text>
                    <Text className="brand-subtitle">企业知识助手</Text>
                  </div>
                </div>
              )}
              <Tooltip title={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'}>
                <Button
                  type="text"
                  icon={sidebarCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                  onClick={() => setSidebarCollapsed((current) => !current)}
                />
              </Tooltip>
            </div>

            <div className="sidebar-actions">
              <Tooltip title="新对话">
                <Button type="primary" icon={<PlusOutlined />} block={!sidebarCollapsed} onClick={startNewConversation}>
                  {!sidebarCollapsed && '新对话'}
                </Button>
              </Tooltip>
            </div>

            <div className="session-list">
              {!sidebarCollapsed && (
                <div className="session-group-label">
                  <HistoryOutlined />
                  <span>会话</span>
                </div>
              )}

              {orderedSessions.length === 0 ? (
                <div className="empty-sidebar">暂无会话</div>
              ) : (
                orderedSessions.map((item) => {
                  const active = item.session_id === sessionId;
                  return (
                    <button
                      key={item.session_id}
                      type="button"
                      className={`session-item ${active ? 'is-active' : ''}`}
                      onClick={() => handleSwitchSession(item.session_id)}
                    >
                      <MessageOutlined className="session-item-icon" />
                      {!sidebarCollapsed && (
                        <span className="session-item-body">
                          <span className="session-item-title">{item.title}</span>
                          <span className="session-item-preview">{item.preview || '暂无预览'}</span>
                          <span className="session-item-meta">
                            {formatSessionTime(item.updated_at)} · {item.turn_count} 轮
                          </span>
                        </span>
                      )}
                    </button>
                  );
                })
              )}
            </div>
          </aside>

          <main className="workspace-main">
            <header className="thread-header">
              <div className="thread-heading">
                <Title level={4}>{activeSessionSummary?.title || '新对话'}</Title>
                <div className="thread-meta">
                  <Tag>{activeSessionSummary?.turn_count ?? 0} 轮</Tag>
                  <Tag>{sessionMessages.length} 条消息</Tag>
                </div>
              </div>

              <div className="thread-tools">
                <Segmented
                  size="small"
                  value={exportFormat}
                  onChange={(value) => setExportFormat(value as 'json' | 'md')}
                  options={[
                    { label: 'MD', value: 'md' },
                    { label: 'JSON', value: 'json' },
                  ]}
                />
                <Tooltip title="导出会话">
                  <Button
                    icon={exportFormat === 'md' ? <FileMarkdownOutlined /> : <DownloadOutlined />}
                    onClick={exportSession}
                    loading={loadingHistory}
                  />
                </Tooltip>
                <Tooltip title="清空当前会话">
                  <Button danger icon={<ClearOutlined />} onClick={onClearSession} loading={loading} />
                </Tooltip>
              </div>
            </header>

            <section className="thread-scroll">
              <div className="thread-feed">
                {loadingHistory ? (
                  <div className="state-panel">
                    <Spin />
                    <Text type="secondary">正在加载会话历史</Text>
                  </div>
                ) : visibleMessages.length === 0 ? (
                  <div className="welcome-panel">
                    <RobotOutlined />
                    <Title level={3}>今天想了解什么？</Title>
                    <Paragraph>直接提问，我会基于已接入的知识库给出清晰回答，并在需要时附上参考内容。</Paragraph>
                  </div>
                ) : (
                  visibleMessages.map((item) => {
                    const isUser = item.role === 'user';
                    return (
                      <article key={item.message_id} className={`message ${isUser ? 'from-user' : 'from-assistant'}`}>
                        <div className="message-avatar">{isUser ? <UserOutlined /> : <RobotOutlined />}</div>
                        <div className="message-content">
                          <div className="message-topline">
                            <Text strong>{isUser ? '你' : '助手'}</Text>
                            <Text type="secondary">#{item.seq}</Text>
                            <Text type="secondary">{item.created_at}</Text>
                          </div>
                          <Paragraph>{item.text}</Paragraph>
                        </div>
                      </article>
                    );
                  })
                )}

                {loading && (
                  <article className="message from-assistant">
                    <div className="message-avatar">
                      <RobotOutlined />
                    </div>
                    <div className="message-content is-thinking">
                      <div className="message-topline">
                        <Text strong>助手</Text>
                        <Text type="secondary">正在生成</Text>
                      </div>
                      <div className="typing-indicator">
                        <span />
                        <span />
                        <span />
                      </div>
                    </div>
                  </article>
                )}

                {error && <Alert type="error" showIcon message="请求失败" description={error} />}

                {result && (
                  <section className="inspector-panel">
                    <div className="inspector-header">
                      <Text strong>参考内容</Text>
                    </div>
                    <div className="inspector-grid">
                      <div className="inspector-block">
                        <Text type="secondary">你的问题</Text>
                        <Paragraph>{result.question}</Paragraph>
                      </div>
                      <div className="inspector-block">
                        <Text type="secondary">理解后的问题</Text>
                        <Paragraph>{result.rewritten_question}</Paragraph>
                      </div>
                    </div>
                    <div className="inspector-block">
                      <Text type="secondary">回答</Text>
                      <Paragraph>{result.answer}</Paragraph>
                    </div>
                    <div className="context-list">
                      <Text type="secondary">引用上下文</Text>
                      {result.contexts.length === 0 ? (
                        <Paragraph type="secondary">没有返回上下文。</Paragraph>
                      ) : (
                        result.contexts.map((item) => (
                          <div key={item.index} className="context-item">
                            <div className="context-meta">
                              <Tag>片段 {item.index}</Tag>
                              <span>{item.title_path || 'ROOT'}</span>
                              <span>{item.source || 'unknown'}</span>
                            </div>
                            <Paragraph>{item.text}</Paragraph>
                          </div>
                        ))
                      )}
                    </div>
                  </section>
                )}

                <div ref={feedEndRef} />
              </div>
            </section>

            <section className="composer">
              <Form form={form} layout="vertical" onFinish={onFinish}>
                <Form.Item name="question" rules={[{ required: true, message: '请输入问题' }]}>
                  <Input.TextArea
                    autoSize={{ minRows: 2, maxRows: 7 }}
                    placeholder="输入你的问题，Ctrl / Command + Enter 发送"
                    onKeyDown={(event) => {
                      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
                        event.preventDefault();
                        form.submit();
                      }
                    }}
                  />
                </Form.Item>

                <div className="composer-footer">
                  <Text type="secondary">答案将基于知识库生成</Text>
                  <Button type="primary" htmlType="submit" icon={<SendOutlined />} loading={loading}>
                    发送
                  </Button>
                </div>
              </Form>
            </section>
          </main>
        </div>
      </AntApp>
    </ConfigProvider>
  );
}
