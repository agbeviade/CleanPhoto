import 'dart:typed_data';
import 'package:flutter/material.dart';
import '../theme.dart';

/// Slider interactif comparant deux images (avant/apres).
/// Glisser horizontalement pour reveler l'image apres.
class BeforeAfterSlider extends StatefulWidget {
  final ImageProvider before;
  final ImageProvider after;
  final double aspectRatio;

  const BeforeAfterSlider({
    super.key,
    required this.before,
    required this.after,
    this.aspectRatio = 4 / 5,
  });

  factory BeforeAfterSlider.fromBytes({
    required Uint8List beforeBytes,
    required Uint8List afterBytes,
    double aspectRatio = 4 / 5,
  }) {
    return BeforeAfterSlider(
      before: MemoryImage(beforeBytes),
      after: MemoryImage(afterBytes),
      aspectRatio: aspectRatio,
    );
  }

  @override
  State<BeforeAfterSlider> createState() => _BeforeAfterSliderState();
}

class _BeforeAfterSliderState extends State<BeforeAfterSlider> {
  double _position = 0.5;

  @override
  Widget build(BuildContext context) {
    return AspectRatio(
      aspectRatio: widget.aspectRatio,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(20),
        child: LayoutBuilder(builder: (context, constraints) {
          final w = constraints.maxWidth;
          final h = constraints.maxHeight;
          return GestureDetector(
            onHorizontalDragUpdate: (d) {
              setState(() {
                _position = (_position + d.delta.dx / w).clamp(0.0, 1.0);
              });
            },
            onTapDown: (d) {
              setState(() => _position = (d.localPosition.dx / w).clamp(0.0, 1.0));
            },
            child: Stack(
              fit: StackFit.expand,
              children: [
                // After (background)
                Image(image: widget.after, fit: BoxFit.cover),
                // Before (clipped to position)
                ClipRect(
                  clipper: _RightClipper(_position),
                  child: Image(image: widget.before, fit: BoxFit.cover),
                ),
                // Labels
                Positioned(
                  top: 12,
                  left: 12,
                  child: _label('AVANT', AppColors.textDark.withOpacity(0.85)),
                ),
                Positioned(
                  top: 12,
                  right: 12,
                  child: _label('APRES', AppColors.primaryBlue),
                ),
                // Divider line + handle
                Positioned(
                  left: w * _position - 1,
                  top: 0,
                  bottom: 0,
                  width: 2,
                  child: Container(color: Colors.white),
                ),
                Positioned(
                  left: w * _position - 22,
                  top: h / 2 - 22,
                  child: Container(
                    width: 44,
                    height: 44,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withOpacity(0.25),
                          blurRadius: 8,
                          offset: const Offset(0, 2),
                        ),
                      ],
                    ),
                    child: Transform.rotate(
                      angle: 1.5708,
                      child: const Icon(Icons.unfold_more,
                          color: AppColors.primaryBlue, size: 26),
                    ),
                  ),
                ),
              ],
            ),
          );
        }),
      ),
    );
  }

  Widget _label(String text, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.92),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: color,
          letterSpacing: 1.1,
        ),
      ),
    );
  }
}

class _RightClipper extends CustomClipper<Rect> {
  final double position;
  _RightClipper(this.position);
  @override
  Rect getClip(Size size) => Rect.fromLTWH(0, 0, size.width * position, size.height);
  @override
  bool shouldReclip(_RightClipper oldClipper) => oldClipper.position != position;
}
