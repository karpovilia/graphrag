import { jsonParse } from "@krainovsd/js-helpers";
import fs from "fs/promises";
import path from "path";
import type { ICityGraphImportMap } from "@/entities/cities";

export default defineEventHandler(async (event) => {
  try {
    const formData = await readFormData(event);
    
    const token = formData.get('token') as string;
    const model = formData.get('model') as string;
    const algorithm = formData.get('algorithm') as string;
    const language = formData.get('language') as string;
    const files = formData.getAll('files') as File[];

    if (!token || !model || !algorithm || !language || !files || files.length === 0) {
      throw createError({
        statusCode: 400,
        statusMessage: "Missing required fields",
      });
    }
    console.log(token, model, algorithm, language, files);

    return { 
      success: true, 
      message: "Graph imported successfully" 
    };
  } catch (error: any) {
    console.error("Import error:", error);
    
    throw createError({
      statusCode: error.statusCode || 500,
      statusMessage: error.statusMessage || "Error importing graph",
    });
  }
});

