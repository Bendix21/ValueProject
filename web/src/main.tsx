import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import "./styles.css";
import App from "./App";
import NewJob from "./pages/NewJob";
import JobDetail from "./pages/JobDetail";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<NewJob />} />
          <Route path="jobs/:jobId" element={<JobDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
