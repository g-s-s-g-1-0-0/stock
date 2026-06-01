import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
  componentStack: string | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null, componentStack: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error, componentStack: null }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 콘솔을 볼 수 없는 모바일 환경을 위해 화면에도 표시하지만, 데스크톱 디버깅을 위해 로그도 남긴다.
    console.error('[ErrorBoundary]', error, info.componentStack)
    this.setState({ error, componentStack: info.componentStack ?? null })
  }

  render() {
    const { error, componentStack } = this.state
    if (!error) return this.props.children

    return (
      <div
        style={{
          maxWidth: 720,
          margin: '0 auto',
          padding: '24px 16px',
          fontFamily: 'system-ui, -apple-system, sans-serif',
          color: '#1f2937',
          lineHeight: 1.5,
          wordBreak: 'break-word',
        }}
      >
        <h1 style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>화면을 표시하는 중 오류가 발생했어요</h1>
        <p style={{ fontSize: 14, color: '#4b5563', marginBottom: 16 }}>
          아래 오류 내용을 캡처해서 전달해 주시면 빠르게 고칠 수 있어요.
        </p>
        <pre
          style={{
            background: '#f3f4f6',
            border: '1px solid #e5e7eb',
            borderRadius: 8,
            padding: 12,
            fontSize: 12,
            whiteSpace: 'pre-wrap',
            overflowX: 'auto',
          }}
        >
          {error.name}: {error.message}
          {error.stack ? `\n\n${error.stack}` : ''}
          {componentStack ? `\n\n[component]${componentStack}` : ''}
        </pre>
        <button
          type="button"
          onClick={() => window.location.reload()}
          style={{
            marginTop: 16,
            padding: '10px 16px',
            fontSize: 14,
            fontWeight: 600,
            color: '#fff',
            background: '#2563eb',
            border: 'none',
            borderRadius: 8,
            cursor: 'pointer',
          }}
        >
          새로고침
        </button>
      </div>
    )
  }
}
