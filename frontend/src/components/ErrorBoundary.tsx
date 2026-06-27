import React from 'react';
import styles from './ErrorBoundary.module.css';

interface Props {
  children: React.ReactNode;
  /** Optional label shown in the fallback for context (e.g. widget name). */
  label?: string;
}

interface State {
  hasError: boolean;
}

export default class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Log to console in dev; swap for a real logging service later.
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  handleRetry = () => {
    this.setState({ hasError: false });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className={styles.fallback} role="alert">
          <span className={styles.icon} aria-hidden="true">!</span>
          <span className={styles.message}>
            {this.props.label
              ? `"${this.props.label}" yüklenemedi`
              : 'Bu bölüm yüklenemedi'}
          </span>
          <button className={styles.retryBtn} onClick={this.handleRetry}>
            Tekrar dene
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
