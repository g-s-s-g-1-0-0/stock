import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    const { error } = this.state
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
        <h1 style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>화면을 불러오지 못했습니다</h1>
        <p style={{ fontSize: 14, color: '#4b5563', marginBottom: 16 }}>
          새로고침 후 다시 시도해 주세요.
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          style={{
            marginTop: 8,
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
