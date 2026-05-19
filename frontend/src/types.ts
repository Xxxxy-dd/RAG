export interface ContextChunk {
  index: number;
  text: string;
  source: string | null;
  title_path: string | null;
  retrieval_score: number | null;
  rerank_score: number | null;
}

export interface QARequest {
  question: string;
  history?: string[] | null;
  session_id?: string | null;
  top_k?: number;
  top_n?: number;
  use_query_rewrite?: boolean;
  collection_name?: string;
  persist_directory?: string | null;
}

export interface QAResponse {
  question: string;
  rewritten_question: string;
  answer: string;
  contexts: ContextChunk[];
}
