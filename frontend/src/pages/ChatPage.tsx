/**
 * Route wrapper for the Ocean Assistant.
 *
 * The page itself lives in `features/assistant/`, which is where the
 * assistant-ui runtime, the SSE adapter and the provenance UI belong. This
 * file stays only because `app/App.tsx` lazy-imports routes from `pages/`.
 *
 * `ChatPage.legacy.tsx` is the previous hand-rolled, non-streaming
 * implementation. It is kept until the streaming page has run in anger — it is
 * the only reference for how several details behaved, and it still works
 * against the unchanged `POST /api/v1/chat`.
 */
export { AssistantPage as ChatPage } from '../features/assistant/AssistantPage';
