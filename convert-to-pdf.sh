#!/bin/bash
# Convert all course markdown files to PDF
# Usage: ./convert-to-pdf.sh

WEASYPRINT="/opt/homebrew/opt/python@3.9/Frameworks/Python.framework/Versions/3.9/bin/weasyprint"
CSS="pdf/style.css"
OUTDIR="pdf"

# Map of source md -> output pdf
declare -a FILES=(
  "课程大纲.md|课程大纲.pdf"
  "README.md|README.pdf"
  "part1-principles/module0-core-mechanism.md|part1-module0-核心机制.pdf"
  "part1-principles/module1-grounding.md|part1-module1-Grounding感知.pdf"
  "part1-principles/module2-foundation-models.md|part1-module2-底层模型.pdf"
  "part2-strategies/module3-planning.md|part2-module3-Planning规划.pdf"
  "part2-strategies/module4-action.md|part2-module4-Action执行.pdf"
  "part2-strategies/module5-feedback.md|part2-module5-Feedback反馈.pdf"
  "part2-strategies/module6-search-strategies.md|part2-module6-搜索策略.pdf"
  "part3-practice/module7-engineering-practice.md|part3-module7-工程实战.pdf"
  "part3-practice/module8-build-your-own.md|part3-module8-构建你自己的编程代理.pdf"
  "appendix/paper-list.md|appendix-论文清单.pdf"
)

echo "Converting markdown files to PDF..."
echo "======================================"

for entry in "${FILES[@]}"; do
  SRC="${entry%%|*}"
  DST="${entry##*|}"

  if [ ! -f "$SRC" ]; then
    echo "⚠ SKIP: $SRC (not found)"
    continue
  fi

  echo -n "📄 $SRC → $OUTDIR/$DST ... "

  # MD -> HTML via pandoc, then HTML -> PDF via weasyprint
  pandoc "$SRC" \
    --from=markdown \
    --to=html5 \
    --standalone \
    --metadata title="" \
    -o "/tmp/_course_tmp.html" 2>/dev/null

  "$WEASYPRINT" \
    --stylesheet="$CSS" \
    "/tmp/_course_tmp.html" \
    "$OUTDIR/$DST" 2>/dev/null

  if [ $? -eq 0 ]; then
    echo "✓"
  else
    echo "✗ FAILED"
  fi
done

rm -f /tmp/_course_tmp.html
echo "======================================"
echo "Done! PDFs are in ./$OUTDIR/"
